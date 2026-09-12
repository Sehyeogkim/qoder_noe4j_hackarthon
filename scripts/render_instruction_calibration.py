#!/usr/bin/env python3
"""Compose actual baseline/calibration recordings; never impersonate agent retrieval."""
import argparse
import json
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw

from render_first_demo import INK, MUTED, TEAL, ORANGE, font, text_box, sha256, load_attempt, active_decision

PROPOSED_INSTRUCTION = ('Pick up the black bowl from the center of the table and place it on the plate. '
    'Approach the bowl with the gripper open, lower the fingers around its rim, then close the gripper. '
    'Confirm that the bowl rises with the gripper before moving toward the plate. '
    'Lower the bowl onto the plate and release it.')


def recorded_asset(reference, artifact_root):
    prefix = '/workspace/arma/artifacts/'
    if not reference.startswith(prefix):
        raise ValueError('Expected a recorded worker artifact path')
    relative = Path(reference[len(prefix):])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe worker artifact reference')
    path = (artifact_root / relative).resolve(strict=True)
    if not path.is_relative_to(artifact_root.resolve()) or not path.is_file():
        raise ValueError('Worker asset escapes local artifact root')
    return path


def load_probe(path, artifact_root):
    attempt = json.loads(path.read_text())
    if attempt['condition'] != 'diagnostic_instruction_probe':
        raise ValueError('This renderer only accepts the explicitly labeled diagnostic condition')
    decisions = attempt['decisions']
    frames = [recorded_asset(decisions[0]['execution']['observation_before']['rgb_ref'], artifact_root)]
    step = 0
    for decision in decisions:
        execution = decision['execution']
        if execution['start_step_index'] != step:
            raise ValueError('Non-contiguous calibration execution')
        for action in execution['actions']:
            step += 1
            if action['step_index'] != step:
                raise ValueError('Non-contiguous calibration action')
            frames.append(recorded_asset(action['rgb_ref'], artifact_root))
        if execution['end_step_index'] != step:
            raise ValueError('Calibration interval count mismatch')
    if step != attempt['step_index']:
        raise ValueError('Calibration final count mismatch')
    return {'attempt': attempt, 'decisions': decisions, 'frames': frames,
            'video': recorded_asset(attempt['video_ref'], artifact_root), 'source': path}


def validate(left, right):
    a, b = left['attempt'], right['attempt']
    for key in ('task_id', 'task_goal', 'robot_id', 'policy_id', 'seed', 'init_state_id', 'perception_mode'):
        if a.get(key) is None or a.get(key) != b.get(key):
            raise ValueError('Comparison mismatch: ' + key)
    for trace in (left, right):
        attempt = trace['attempt']
        if attempt['status'] != 'completed' or attempt['provenance'] != 'real_execution':
            raise ValueError('Only completed actual recordings are accepted')
        if attempt['manifest']['video_fps'] != 20:
            raise ValueError('Only recorded 20 fps media is supported')
    if a['outcome'] != 'failure' or b['outcome'] != 'success':
        raise ValueError('Requested actual failure/success pair is unavailable')
    if not right['decisions'][-1]['execution']['task_success']:
        raise ValueError('Successful probe lacks environment success evidence')
    if sha256(left['frames'][0]) != sha256(right['frames'][0]):
        raise ValueError('Initial RGB mismatch')


def panel(canvas, trace, index, x, title, accent, hold=False, proposal=False):
    draw = ImageDraw.Draw(canvas)
    attempt = trace['attempt']; last = attempt['step_index']; step = min(index, last)
    terminal = index >= last
    held = index > last or hold
    decision = active_decision(trace, step)
    draw.rounded_rectangle((x, 190, x+910, 1014), radius=18, fill='white', outline='#d5e2ed', width=2)
    text_box(draw, title, (x+24, 210), 860, 70, 29, fill=accent)
    draw.text((x+24, 278), f'Action {step}/{last}  ·  Simulator {step/20:.2f}s', font=font(24), fill=MUTED)
    with Image.open(trace['frames'][step]) as source:
        size = 370 if proposal else 480
        rgb = source.convert('RGB').resize((size,size), Image.Resampling.LANCZOS)
        canvas.paste(rgb, (x+(910-size)//2, 325))
    if proposal:
        draw.text((x+24, 708), 'INSTRUCTION', font=font(20), fill=ORANGE)
        text_box(draw, PROPOSED_INSTRUCTION, (x+24, 739), 860, 164, 25)
        text_box(draw, 'RECORDED INPUT: ' + decision['execution']['actual_instruction'],
                 (x+24, 914), 860, 44, 19, fill=MUTED)
    else:
        draw.text((x+24, 822), 'EXACT INSTRUCTION SENT TO OPENVLA', font=font(17), fill=MUTED)
        text_box(draw, decision['execution']['actual_instruction'], (x+24, 857), 860, 89, 29)
    result = ('ENVIRONMENT: ' + attempt['outcome'].upper()) if terminal else 'EXECUTING · outcome not yet reached'
    if held:
        result += ' · FINAL FRAME HELD'
    text_box(draw, result, (x+24, 968), 862, 32, 22, fill=accent if terminal else MUTED)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-bundle', type=Path, required=True)
    parser.add_argument('--probe-attempt', type=Path, required=True)
    parser.add_argument('--artifact-root', type=Path, default=Path('artifacts'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--show-proposal', action='store_true', help='Display a clearly labeled unexecuted authored instruction alongside the actual input.')
    args = parser.parse_args()
    left = load_attempt(args.baseline_bundle.resolve(), 'baseline')
    right = load_probe(args.probe_attempt.resolve(), args.artifact_root.resolve())
    validate(left, right)
    output = args.output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    total = max(len(left['frames']), len(right['frames']))
    hold = 60
    writer = imageio_ffmpeg.write_frames(str(output), (1920,1080), fps=20, codec='libx264', quality=8,
        macro_block_size=1, output_params=['-movflags','+faststart'], ffmpeg_log_level='warning')
    writer.send(None)
    try:
        for index in range(total + hold):
            step = min(index, total-1)
            canvas = Image.new('RGB', (1920,1080), '#f4f7fb'); draw = ImageDraw.Draw(canvas)
            draw.text((32,26), 'Algorithm illustration · recorded robot footage' if args.show_proposal else 'Same initial state · frozen policy', font=font(44), fill=INK)
            draw.text((34,87), f'REAL RECORDED EXECUTIONS  ·  Initialization {left["attempt"]["init_state_id"]}  ·  Same initial RGB and policy weights', font=font(22), fill=TEAL)
            text_box(draw, 'Original goal: ' + left['attempt']['task_goal'], (34,129), 1840, 50, 25)
            panel(canvas,left,step,30,'Frozen OpenVLA · baseline',TEAL,index>=total)
            panel(canvas,right,step,980,'Instruction refinement' if args.show_proposal else 'Frozen OpenVLA · recorded successful instruction',ORANGE,index>=total,proposal=args.show_proposal)
            footer = ('Long-form text explains the algorithm. The recorded success used the shorter instruction shown below.' if args.show_proposal else 'Instruction calibration replay; agent retrieval not shown.  |  Recorded simulator time, 20 fps; terminal frames held.')
            draw.text((34,1040),footer,font=font(20),fill=MUTED)
            writer.send(canvas.tobytes())
            if index in (119,120,total+hold-1):
                suffix = '.png' if index == total+hold-1 else f'-action-{index}.png'
                canvas.save(output.with_name(output.stem+suffix))
    finally:
        writer.close()
    metadata = {'schema_version':'1','comparison':'baseline_vs_direct_instruction_calibration',
        'agent_retrieval_shown':False,'provenance':'real_execution','same_state_calibrated':True,
        'limitations':['The successful side is a direct instruction probe, not an autonomous memory retrieval result.',
            'Selected same-state recordings do not establish held-out generalization or aggregate improvement.'],
        'original_goal':left['attempt']['task_goal'], 'initial_rgb_sha256':sha256(left['frames'][0]),
        'fps':20,'recorded_frame_count':total,'final_hold_frame_count':hold,'final_hold_seconds':3,
        'frame_count':total+hold,'duration_s':(total+hold)/20,'output_sha256':sha256(output),
        'sides':{}}
    if args.show_proposal:
        metadata['proposed_instruction'] = {'text': PROPOSED_INSTRUCTION, 'executed_in_recording': False,
            'authorship': 'authored illustration, not an actual agent quotation'}
    for name,trace,source in [('baseline',left,args.baseline_bundle),('instruction_calibration',right,args.probe_attempt)]:
        attempt=trace['attempt']
        metadata['sides'][name]={'attempt_id':attempt['attempt_id'],'condition':attempt['condition'],
            'source_path':str(source.resolve()),'source_sha256':sha256(source),'video_path':str(trace['video']),
            'video_sha256':sha256(trace['video']),'outcome':attempt['outcome'],'action_count':attempt['step_index'],
            'termination_reason':attempt['termination_reason'],'elapsed_ms':attempt.get('elapsed_ms'),
            'instruction_timeline':[{'start_action':d['execution']['start_step_index'],
                'end_action':d['execution']['end_step_index'],'actual_instruction':d['execution']['actual_instruction']} for d in trace['decisions']]}
    output.with_suffix('.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps({'output':str(output),'frames':total+hold,'sha256':metadata['output_sha256']}))


if __name__ == '__main__':
    main()
