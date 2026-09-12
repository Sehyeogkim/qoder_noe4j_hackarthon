from datetime import datetime,timedelta,timezone
import json
import httpx
import pytest
from arma.cloud import OwnedPod,RunPodV2,Watchdog,assert_dispatch_window,register_owned_pod

NOW=datetime(2026,9,12,20,tzinfo=timezone.utc)
TOKEN='unit-test-ownership-token'

def pod():
    return {'id':'owned123','name':'arma-astras-unit','createdAt':NOW.isoformat(),
            'env':{'ARMA_OWNER_TOKEN':TOKEN},'gpu':{'id':'NVIDIA A40','count':1},'mounts':{'persistent':{'size':60}},'cost':.49}

def register(tmp_path,**overrides):
    path=tmp_path/'owned-pod.json'
    args=dict(creation_request_id='created-by-this-run',ownership_token=TOKEN,hourly_gpu_rate=.49,
              hourly_disk_rate=.003,hourly_volume_rate=.018,authorized_new_pod=True,now=NOW,approved_gpu_id='NVIDIA A40',budget_path=tmp_path/'budget.sqlite')
    args.update(overrides)
    return path,register_owned_pod(path,pod(),**args)

class FakeAPI:
    def __init__(self):
        self.live=pod();self.deleted=[]
    def get_pod(self,identifier):
        assert identifier=='owned123'
        return self.live
    def delete_pod(self,identifier):
        self.deleted.append(identifier);self.live=None


def test_deadline_max_six_hours_with_shutdown_margin(tmp_path):
    path,owner=register(tmp_path)
    assert owner.deadline==NOW+timedelta(hours=6,seconds=-300)
    assert (owner.deadline-NOW).total_seconds()/3600*owner.hourly_rate<5


def test_high_rates_shorten_lifetime():
    owner=OwnedPod(pod_id='p',pod_name='arma-astras-cost',created_at=NOW,registered_at=NOW,
        ownership_token=TOKEN,creation_request_id='new',authorized_new_pod=True,
        hourly_gpu_rate=2,hourly_disk_rate=.1,hourly_volume_rate=.1)
    seconds=(owner.deadline-NOW).total_seconds()
    assert seconds<6*3600
    assert (seconds+300)/3600*owner.hourly_rate==pytest.approx(4.75)


def test_registration_refuses_existing_manifest_old_pod_or_unapproved(tmp_path):
    path,owner=register(tmp_path)
    with pytest.raises(FileExistsError):register(tmp_path)
    with pytest.raises(ValueError):
        register(tmp_path/'old',now=NOW+timedelta(hours=2))
    with pytest.raises(ValueError):
        register(tmp_path/'unauthorized',authorized_new_pod=False)


def test_watcher_only_deletes_exact_owned_pod_at_deadline_without_archive(tmp_path):
    path,owner=register(tmp_path)
    api=FakeAPI();guard=Watchdog(path,api)
    assert guard.tick(NOW)['state']=='watching'
    assert not api.deleted
    result=guard.tick(owner.deadline)
    assert api.deleted==['owned123'] and result['state']=='deleted'
    assert result['artifact_risk'] is True


def test_mismatched_live_resource_never_deleted(tmp_path):
    path,owner=register(tmp_path)
    api=FakeAPI();api.live['name']='another-project'
    with pytest.raises(ValueError,match='ownership'):
        Watchdog(path,api).tick(owner.deadline)
    assert not api.deleted


def test_network_volume_refused(tmp_path):
    path,owner=register(tmp_path)
    api=FakeAPI();api.live['mounts']['network']={'id':'unrelated-volume'}
    with pytest.raises(ValueError,match='network volume'):
        Watchdog(path,api).tick(owner.deadline)
    assert not api.deleted


def test_dispatch_requires_fresh_watchdog_and_sufficient_time(tmp_path):
    path,owner=register(tmp_path)
    with pytest.raises(RuntimeError,match='watchdog'):
        assert_dispatch_window(path,now=NOW)
    Watchdog(path,FakeAPI()).tick(NOW)
    assert assert_dispatch_window(path,now=NOW)>120
    with pytest.raises(RuntimeError,match='stale'):
        assert_dispatch_window(path,now=NOW+timedelta(seconds=91))
    with pytest.raises(RuntimeError,match='deadline'):
        assert_dispatch_window(path,now=owner.deadline)


def test_official_rest_v2_bearer_get_delete_contract():
    calls=[]
    def handle(request):
        calls.append((request.method,request.url.path,request.headers['Authorization']))
        return httpx.Response(200,json=pod()) if request.method=='GET' else httpx.Response(204)
    api=RunPodV2('fake-not-real-key',transport=httpx.MockTransport(handle))
    assert api.get_pod('owned123')['id']=='owned123'
    api.delete_pod('owned123');api.close()
    assert calls==[('GET','/v2/pods/owned123','Bearer fake-not-real-key'),('DELETE','/v2/pods/owned123','Bearer fake-not-real-key')]


def test_watchdog_detects_manifest_tampering(tmp_path):
    path,owner=register(tmp_path)
    api=FakeAPI();watcher=Watchdog(path,api)
    path.write_text(path.read_text()+' ')
    with pytest.raises(RuntimeError,match='changed'):
        watcher.tick(owner.deadline)
    assert not api.deleted


def test_live_rate_increase_accelerates_cutoff(tmp_path):
    path,owner=register(tmp_path)
    api=FakeAPI();api.live['cost']=10
    result=Watchdog(path,api).tick(NOW+timedelta(hours=1))
    assert result['state']=='deleted'
    assert api.deleted==['owned123']


def test_compute_reservation_charged_once_and_retained_until_actual_bill(tmp_path):
    from arma.budget import Budget, BudgetExceeded
    from arma.cloud import settle_verified_compute_bill
    path,owner=register(tmp_path)
    budget=Budget(tmp_path/'budget.sqlite')
    assert budget.totals()['compute']==5
    with pytest.raises(BudgetExceeded):budget.reserve(.01,category='compute')
    guard=Watchdog(path,FakeAPI())
    guard.tick(NOW);guard.tick(NOW+timedelta(seconds=30));guard.tick(owner.deadline)
    assert budget.totals()['compute']==5
    settle_verified_compute_bill(path,2.10,'test-final-billing-record')
    assert budget.totals()['compute']==2.10


def test_l40s_is_default_and_requires_explicit_matching_gpu(tmp_path):
    data=pod();data['gpu']['id']='NVIDIA L40S';data['cost']=.79
    owner=register_owned_pod(tmp_path/'l40s.json',data,creation_request_id='l40s-create',
        ownership_token=TOKEN,hourly_gpu_rate=.79,hourly_disk_rate=.003,hourly_volume_rate=.018,
        authorized_new_pod=True,now=NOW,budget_path=tmp_path/'budget.sqlite')
    assert owner.gpu_id=='NVIDIA L40S'


def test_one_compute_reservation_cannot_fund_second_pod(tmp_path):
    path,owner=register(tmp_path)
    other=pod();other['id']='other-owned-id'
    with pytest.raises(ValueError,match='another pod'):
        register_owned_pod(tmp_path/'second.json',other,creation_request_id='second-create',
            ownership_token=TOKEN,hourly_gpu_rate=.49,hourly_disk_rate=.003,hourly_volume_rate=.018,
            authorized_new_pod=True,now=NOW,approved_gpu_id='NVIDIA A40',
            budget_path=tmp_path/'budget.sqlite',budget_reservation_id=owner.budget_reservation_id)


def test_replacement_retains_old_upper_bound_unsettled_and_total_five(tmp_path):
    from arma.budget import Budget
    from arma.cloud import record_verified_deletion,retain_deleted_pod_upper_bound,reserve_compute_before_create
    path,old=register(tmp_path)
    api=FakeAPI();api.live=None
    record_verified_deletion(path,api,now=NOW+timedelta(minutes=10))
    assert retain_deleted_pod_upper_bound(path,1)==1
    ledger=Budget(tmp_path/'budget.sqlite')
    with ledger._db() as db:
        charge=db.execute('SELECT amount,settled,metadata FROM charges WHERE id=?',(old.budget_reservation_id,)).fetchone()
    assert charge[0]==1 and charge[1]==0
    assert json.loads(charge[2])['state']=='estimated_upper_bound_unsettled'
    assert json.loads(charge[2])['billing_confirmed'] is False
    replacement_reservation=reserve_compute_before_create(tmp_path/'budget.sqlite')
    replacement=pod();replacement['id']='replacement';replacement['name']='arma-astras-replacement'
    replacement['gpu']['id']='NVIDIA L40S';replacement['cost']=1.09
    replacement['createdAt']=(NOW+timedelta(minutes=11)).isoformat()
    new=register_owned_pod(tmp_path/'replacement.json',replacement,creation_request_id='replacement-create',
        ownership_token=TOKEN,hourly_gpu_rate=1.09,hourly_disk_rate=.003,hourly_volume_rate=.018,
        authorized_new_pod=True,now=NOW+timedelta(minutes=11),budget_path=tmp_path/'budget.sqlite',
        budget_reservation_id=replacement_reservation)
    assert new.compute_budget_usd==4
    assert ledger.totals()['compute']==5
    assert new.budget_reservation_id!=old.budget_reservation_id


def test_upper_bound_release_requires_signed_absence_and_sufficient_retention(tmp_path):
    from arma.cloud import record_verified_deletion,retain_deleted_pod_upper_bound
    path,old=register(tmp_path)
    api=FakeAPI()
    with pytest.raises(ValueError,match='still present'):
        record_verified_deletion(path,api,now=NOW+timedelta(minutes=10))
    with pytest.raises(FileNotFoundError):retain_deleted_pod_upper_bound(path,1)
    api.live=None
    record_verified_deletion(path,api,now=NOW+timedelta(minutes=10))
    with pytest.raises(ValueError,match='at least'):
        retain_deleted_pod_upper_bound(path,.01)
    proof_path=tmp_path/'owned-pod.json.deletion-proof.json'
    proof=json.loads(proof_path.read_text());proof['payload']['verified_terminated_at']=NOW.isoformat()
    proof_path.write_text(json.dumps(proof))
    with pytest.raises(ValueError,match='signature'):
        retain_deleted_pod_upper_bound(path,1)
