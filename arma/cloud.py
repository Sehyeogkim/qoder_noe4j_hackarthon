"""Attributed RunPod lifetime guard. Importing this module never calls RunPod.

REST v2 GET/DELETE paths and bearer auth verified against:
https://api.runpod.io/v2/openapi.json (2026-09-12).
Only an explicitly registered newly created ARMA pod can be terminated.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import math
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .budget import Budget


def utcnow():
    return datetime.now(timezone.utc)


def parse_time(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
    if result.tzinfo is None:
        raise ValueError('UTC-aware timestamps required')
    return result.astimezone(timezone.utc)


class OwnedPod(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    schema_version: Literal[1]=1
    project: Literal['ARMA-Astras']='ARMA-Astras'
    pod_id: str=Field(pattern=r'^[A-Za-z0-9_-]+$')
    pod_name: str=Field(pattern=r'^arma-astras-[A-Za-z0-9_-]+$')
    created_at: datetime
    registered_at: datetime
    ownership_token: str=Field(min_length=16,max_length=100)
    creation_request_id: str=Field(min_length=1,max_length=100)
    authorized_new_pod: Literal[True]
    gpu_id: Literal['NVIDIA L40S','NVIDIA A40']='NVIDIA L40S'
    budget_ledger: str | None=None
    budget_reservation_id: str | None=None
    gpu_count: Literal[1]=1
    hourly_gpu_rate: float=Field(gt=0)
    hourly_disk_rate: float=Field(ge=0)
    hourly_volume_rate: float=Field(ge=0)
    compute_budget_usd: float=Field(default=5,gt=0,le=5)
    shutdown_reserve_usd: float=Field(default=.25,ge=.25)
    shutdown_margin_seconds: int=Field(default=300,ge=120)
    max_lifetime_hours: float=Field(default=6,gt=0,le=6)

    @model_validator(mode='after')
    def valid(self):
        self.created_at=parse_time(self.created_at)
        self.registered_at=parse_time(self.registered_at)
        elapsed=(self.registered_at-self.created_at).total_seconds()
        if elapsed < -60 or elapsed > 600:
            raise ValueError('Only a newly created pod can be attributed; register within ten minutes')
        if self.shutdown_reserve_usd>=self.compute_budget_usd:
            raise ValueError('Shutdown reserve must fit compute budget')
        if self.deadline <= self.created_at:
            raise ValueError('Rates leave no usable compute window')
        return self

    @property
    def hourly_rate(self):
        return self.hourly_gpu_rate+self.hourly_disk_rate+self.hourly_volume_rate

    @property
    def deadline(self):
        seconds=min(self.max_lifetime_hours*3600,
                    (self.compute_budget_usd-self.shutdown_reserve_usd)/self.hourly_rate*3600)
        return self.created_at+timedelta(seconds=seconds-self.shutdown_margin_seconds)


def _atomic_json(path, value, *, exclusive=False):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(value,indent=2,sort_keys=True,allow_nan=False).encode()
    descriptor,tmp=tempfile.mkstemp(dir=path.parent,prefix=f'.{path.name}.')
    try:
        with os.fdopen(descriptor,'wb') as out:
            out.write(data);out.flush();os.fsync(out.fileno())
        if exclusive:
            os.link(tmp,path)  # atomic create-without-overwrite, even under races
        else:
            os.replace(tmp,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def verify_identity(owner:OwnedPod,pod:dict):
    if pod.get('id')!=owner.pod_id or pod.get('name')!=owner.pod_name:
        raise ValueError('Live pod ID/name does not match ownership manifest')
    if parse_time(pod.get('createdAt',''))!=owner.created_at:
        raise ValueError('Live pod creation date does not match ownership manifest')
    if pod.get('env',{}).get('ARMA_OWNER_TOKEN')!=owner.ownership_token:
        raise ValueError('Live pod ownership marker mismatch; refusing mutation')
    if pod.get('gpu',{}).get('id')!=owner.gpu_id or pod.get('gpu',{}).get('count')!=1:
        raise ValueError('Only the explicitly authorized single GPU is supported')
    if pod.get('mounts',{}).get('network'):
        raise ValueError('Independent network volume is outside this disposal policy')


def register_owned_pod(path,creation_response:dict,*,creation_request_id:str,
                       ownership_token:str,hourly_gpu_rate:float,hourly_disk_rate:float,
                       hourly_volume_rate:float,authorized_new_pod:bool,now=None,
                       approved_gpu_id='NVIDIA L40S',budget_path='.runtime/budget.sqlite',
                       budget_reservation_id=None):
    """Call immediately after YOUR authorized create request, never on inventory.

    The creation request must contain name=arma-astras-<run> and env marker
    ARMA_OWNER_TOKEN=<random ownership_token>. No API secrets enter this file.
    """
    if Path(path).exists():
        raise FileExistsError(path)
    owner=OwnedPod(pod_id=creation_response['id'],pod_name=creation_response['name'],
        created_at=creation_response['createdAt'],registered_at=now or utcnow(),
        ownership_token=ownership_token,creation_request_id=creation_request_id,
        authorized_new_pod=authorized_new_pod,gpu_id=approved_gpu_id,hourly_gpu_rate=hourly_gpu_rate,
        hourly_disk_rate=hourly_disk_rate,hourly_volume_rate=hourly_volume_rate)
    verify_identity(owner,creation_response)
    if float(creation_response.get('cost',hourly_gpu_rate))>hourly_gpu_rate:
        raise ValueError('Quoted GPU rate exceeds reserved rate')
    ledger=Budget(budget_path)
    reservation=budget_reservation_id
    if reservation:
        with ledger._db() as db:
            charge=db.execute('SELECT category,amount,settled,metadata FROM charges WHERE id=?',(reservation,)).fetchone()
        if not charge or charge[0]!='compute' or not .25<charge[1]<=5 or charge[2]:
            raise ValueError('An unsettled compute reservation above shutdown reserve is required')
        metadata=json.loads(charge[3])
        if metadata.get('pod_id') and metadata['pod_id'] != owner.pod_id:
            raise ValueError('Compute reservation already belongs to another pod')
    else:
        reservation=reserve_compute_before_create(budget_path)
        with ledger._db() as db:
            charge=db.execute('SELECT category,amount,settled,metadata FROM charges WHERE id=?',(reservation,)).fetchone()
    owner.compute_budget_usd=charge[1]
    owner=OwnedPod.model_validate(owner.model_dump())
    owner.budget_ledger=str(Path(budget_path).resolve())
    owner.budget_reservation_id=reservation
    with ledger._db() as db:
        db.execute('BEGIN IMMEDIATE')
        existing=json.loads(db.execute('SELECT metadata FROM charges WHERE id=?',(reservation,)).fetchone()[0])
        if existing.get('pod_id') and existing['pod_id'] != owner.pod_id:
            raise ValueError('Compute reservation already belongs to another pod')
        db.execute('UPDATE charges SET metadata=? WHERE id=?',
            (json.dumps({'pod_id':owner.pod_id,'ownership_manifest':str(Path(path).resolve()),'state':'reserved_pending_billing'}),reservation))
    # The pod already exists. Retain reservation even if the local write fails;
    # this is a potentially billable operation, never a zero-cost cancellation.
    _atomic_json(path,owner.model_dump(mode='json'),exclusive=True)
    return owner


def reserve_compute_before_create(budget_path='.runtime/budget.sqlite',amount=None):
    """Reserve remaining compute allocation (or explicit amount) before creation."""
    ledger=Budget(budget_path)
    amount=ledger.remaining('compute') if amount is None else amount
    if not math.isfinite(amount) or not .25<amount<=5:
        raise ValueError('Compute allocation must exceed shutdown reserve and be at most $5')
    return ledger.reserve(amount,category='compute',metadata={'state':'before_authorized_create'})


def _deletion_key(ledger_path,create=False):
    path=Path(str(ledger_path)+'.deletion-proof-key')
    if create:
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as out:
                out.write(os.urandom(32));out.flush();os.fsync(out.fileno())
        except FileExistsError:
            pass
    data=path.read_bytes()
    if len(data)!=32:raise ValueError('Invalid local deletion proof key')
    return data


def _sign_deletion(payload,key):
    return hmac.new(key,json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()


def record_verified_deletion(manifest_path,api,now=None):
    """READ-only provider confirmation: exact attributed pod must return 404.

    Signs local evidence with a ledger-local private key. It does not delete a
    resource and does not claim that final billing has arrived.
    """
    owner=load_owner(manifest_path)
    if not owner.budget_ledger or not owner.budget_reservation_id:
        raise ValueError('Attributed budget reservation required')
    if api.get_pod(owner.pod_id) is not None:
        raise ValueError('Pod is still present; reservation cannot be released')
    verified_at=parse_time(now or utcnow())
    if verified_at<owner.created_at:raise ValueError('Deletion cannot precede creation')
    payload={'pod_id':owner.pod_id,'state':'deleted','verified_terminated_at':verified_at.isoformat(),
        'observation':'RunPod v2 exact pod GET returned 404',
        'manifest_sha256':hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
        'budget_reservation_id':owner.budget_reservation_id}
    proof={'payload':payload,'signature':_sign_deletion(payload,_deletion_key(owner.budget_ledger,create=True))}
    _atomic_json(str(manifest_path)+'.deletion-proof.json',proof)
    return proof


def retain_deleted_pod_upper_bound(manifest_path,retained_usd=1):
    """Keep conservative UNSETTLED old-pod cost; free only the unused reserve."""
    owner=load_owner(manifest_path)
    if not owner.budget_ledger or not owner.budget_reservation_id:
        raise ValueError('Attributed budget reservation required')
    proof=json.loads(Path(str(manifest_path)+'.deletion-proof.json').read_text())
    payload=proof['payload']
    signature=_sign_deletion(payload,_deletion_key(owner.budget_ledger))
    if not hmac.compare_digest(signature,proof['signature']):
        raise ValueError('Deletion proof signature is invalid')
    if payload.get('pod_id')!=owner.pod_id or payload.get('state')!='deleted' or payload.get('budget_reservation_id')!=owner.budget_reservation_id:
        raise ValueError('Deletion proof identity mismatch')
    if payload.get('manifest_sha256')!=hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest():
        raise ValueError('Deletion proof manifest mismatch')
    elapsed=(parse_time(payload['verified_terminated_at'])-owner.created_at).total_seconds()
    # Use the confirmed-absent time, which is later than actual deletion. Add a
    # separate cash reserve to account for rounding and asynchronous billing.
    minimum=max(0,elapsed)/3600*owner.hourly_rate+owner.shutdown_reserve_usd
    if not math.isfinite(retained_usd) or retained_usd<minimum:
        raise ValueError(f'Retained bound must be at least {minimum:.6f} USD')
    return Budget(owner.budget_ledger).retain_unsettled_upper_bound(owner.budget_reservation_id,retained_usd,
        {'pod_id':owner.pod_id,'deletion_proof_signature':proof['signature'],
         'verified_terminated_at':payload['verified_terminated_at'],
         'minimum_upper_bound_usd':minimum,'actual_bill_received':False})


def settle_verified_compute_bill(manifest_path,actual_usd,billing_reference):
    """Use an actual final billing total; a deletion response is not a bill."""
    owner=load_owner(manifest_path)
    state=json.loads(Path(str(manifest_path)+'.watchdog.json').read_text())
    if state.get('state')!='deleted' or state.get('pod_id')!=owner.pod_id:
        raise ValueError('Verified termination required before final settlement')
    if not billing_reference or actual_usd < 0 or not __import__('math').isfinite(actual_usd):
        raise ValueError('A finite actual total and billing reference are required')
    if not owner.budget_ledger or not owner.budget_reservation_id:
        raise ValueError('No attributed compute reservation')
    Budget(owner.budget_ledger).settle(owner.budget_reservation_id,actual_usd,
        {'pod_id':owner.pod_id,'billing_reference':billing_reference,'state':'actual_bill'})


def load_owner(path):
    return OwnedPod.model_validate_json(Path(path).read_text())


def assert_dispatch_window(path,estimated_seconds=120,now=None):
    """Runner must call before each paid dispatch when a compute manifest is set."""
    owner=load_owner(path)
    now=parse_time(now or utcnow())
    if estimated_seconds<0 or now+timedelta(seconds=estimated_seconds)>=owner.deadline:
        raise RuntimeError('Compute deadline reached; no further work may dispatch')
    state_path=Path(str(path)+'.watchdog.json')
    if not state_path.exists():
        raise RuntimeError('Compute watchdog must be running before paid dispatch')
    state=json.loads(state_path.read_text())
    if state.get('pod_id')!=owner.pod_id or state.get('state')!='watching':
        raise RuntimeError('Compute watchdog is not watching this pod')
    heartbeat_age=(now-parse_time(state['checked_at'])).total_seconds()
    if heartbeat_age>90 or heartbeat_age < -60:
        raise RuntimeError('Compute watchdog heartbeat stale; no paid dispatch')
    deadline=min(owner.deadline,parse_time(state['deadline']))
    if now+timedelta(seconds=estimated_seconds)>=deadline:
        raise RuntimeError('Compute deadline reached; no further work may dispatch')
    return (deadline-now).total_seconds()


class RunPodV2:
    def __init__(self,api_key=None,*,transport=None):
        key=api_key or os.environ['RUNPOD_API_KEY']
        self.client=httpx.Client(base_url='https://api.runpod.io',
            headers={'Authorization':f'Bearer {key}'},timeout=20,transport=transport)
    def get_pod(self,pod_id):
        response=self.client.get(f'/v2/pods/{pod_id}')
        if response.status_code==404:return None
        response.raise_for_status()
        return response.json()
    def delete_pod(self,pod_id):
        response=self.client.delete(f'/v2/pods/{pod_id}')
        if response.status_code not in (204,404):response.raise_for_status()
    def close(self):self.client.close()


class Watchdog:
    def __init__(self,manifest_path,api):
        self.path=Path(manifest_path)
        self.owner=load_owner(self.path)
        self.api=api
        self.manifest_hash=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.confirmed=False

    def tick(self,now=None):
        injected_time=now
        now=parse_time(now or utcnow())
        if hashlib.sha256(self.path.read_bytes()).hexdigest()!=self.manifest_hash:
            raise RuntimeError('Ownership file changed while watchdog was active')
        pod=self.api.get_pod(self.owner.pod_id)
        state={'pod_id':self.owner.pod_id,'checked_at':now.isoformat(),
               'deadline':self.owner.deadline.isoformat(),'state':'watching',
               'compute_reservation_id':self.owner.budget_reservation_id,
               'compute_billing':'reserved_pending_actual_billing'}
        if pod is None:
            state['state']='deleted'
        else:
            verify_identity(self.owner,pod)
            self.confirmed=True
            observed_cost=float(pod.get('cost',self.owner.hourly_gpu_rate))
            # Rising cost accelerates shutdown; it never raises the budget.
            deadline=self.owner.deadline
            if observed_cost>self.owner.hourly_gpu_rate:
                rate=observed_cost+self.owner.hourly_disk_rate+self.owner.hourly_volume_rate
                deadline=min(deadline,self.owner.created_at+timedelta(seconds=
                    (self.owner.compute_budget_usd-self.owner.shutdown_reserve_usd)/rate*3600-self.owner.shutdown_margin_seconds))
            state['deadline']=deadline.isoformat()
            if now>=deadline:
                # Budget cutoff is authoritative even when export failed. This
                # deletes only the attributed disposable pod and attached volume.
                state['state']='terminating'
                state['artifact_risk']=not self._archive_verified()
                _atomic_json(str(self.path)+'.watchdog.json',state)
                self.api.delete_pod(self.owner.pod_id)
                state['state']='deleted' if self.api.get_pod(self.owner.pod_id) is None else 'termination_pending'
        _atomic_json(str(self.path)+'.watchdog.json',state)
        if state['state']=='deleted' and self.owner.budget_ledger:
            record_verified_deletion(self.path,self.api,now=injected_time)
        return state

    def _archive_verified(self):
        path=Path(str(self.path)+'.archive.json')
        if not path.exists():return False
        result=json.loads(path.read_text())
        return result.get('pod_id')==self.owner.pod_id and result.get('sha256_verified') is True

    def run(self,poll_seconds=30):
        if not 1<=poll_seconds<=30:raise ValueError('Poll interval must be at most 30 seconds')
        while True:
            try:
                result=self.tick()
                if result['state']=='deleted':return result
            except (httpx.HTTPError,OSError) as exc:
                # Never log API response bodies or secrets. Keep retrying exact ID.
                print(json.dumps({'watchdog_error':type(exc).__name__,'pod_id':self.owner.pod_id}),flush=True)
            time.sleep(poll_seconds)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ('status','watch'):
        child=sub.add_parser(command);child.add_argument('manifest')
    args=parser.parse_args()
    owner=load_owner(args.manifest)
    if args.command=='status':
        print(json.dumps({'pod_id':owner.pod_id,'deadline':owner.deadline.isoformat(),'hourly_rate':owner.hourly_rate}))
    else:
        api=RunPodV2()
        try:Watchdog(args.manifest,api).run()
        finally:api.close()

if __name__=='__main__':main()
