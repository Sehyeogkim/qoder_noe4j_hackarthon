#!/usr/bin/env python3
"""Prepend a clearly illustrative Korean explanation to an actual calibration replay."""
import argparse
import json
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw

from render_first_demo import INK, MUTED, TEAL, ORANGE, font, text_box, sha256

KOREAN_FONT = '/System/Library/Fonts/AppleSDGothicNeo.ttc'
HANDOFF = '같은 초기 상태에서 이 지시로 성공한 경험이 있습니다. 목표와 관측의 일치 여부를 확인하고, 기록된 지시를 실행 후보로 전달합니다.'
EN_HANDOFF = 'A recorded attempt succeeded with this instruction from the same initial state. Compare the current goal and observation with that experience, then pass the recorded instruction forward as an execution candidate.'


def english_explanation_card(probe):
    canvas = Image.new('RGB', (1920,1080), '#f4f7fb'); draw = ImageDraw.Draw(canvas)
    def text(value, xy, width, height, size, color=INK):
        text_box(draw,value,xy,width,height,size,fill=color)
    text('How a successful experience could guide the next instruction', (40,28),1840,75,44)
    draw.rounded_rectangle((38,112,1882,207),radius=15,fill='#fff1de',outline=ORANGE,width=2)
    text('Illustrative explanation · not an actual agent utterance', (64,137),1780,55,35,ORANGE)
    for box in [(38,235,943,920),(973,235,1882,920)]:
        draw.rounded_rectangle(box,radius=18,fill='white',outline='#d5e2ed',width=2)
    text('01  Facts from the recorded experience', (66,264),845,65,32,TEAL)
    text(f"Initial state {probe['init_state_id']} · frozen OpenVLA\nAuthored instruction: success after {probe['step_index']} actions\nOutcome verified by the LIBERO environment", (66,349),840,195,32)
    text('EXACT INSTRUCTION SENT TO OPENVLA', (66,586),840,45,24,MUTED)
    text(probe['schedule'][0]['instruction'],(66,649),838,143,33)
    text('Agent API calls during this successful run: 0', (66,848),840,44,27,TEAL)
    text('02  Example Memory Retrieval handoff', (1001,264),840,65,32,ORANGE)
    text(EN_HANDOFF,(1001,365),838,322,35)
    text('Retrieve experience → Compare context → Propose instruction', (1001,740),830,100,29,ORANGE)
    text('Example wording to explain the intended architecture.',(1001,848),830,45,24,MUTED)
    text('Next: recorded baseline failure vs. direct instruction success. The footage does not show autonomous memory retrieval.',(42,949),1834,65,26)
    text('Recorded source attempt: '+probe['attempt_id'],(42,1016),1834,37,20,MUTED)
    return canvas


def explanation_card(probe):
    canvas = Image.new('RGB', (1920,1080), '#f4f7fb'); draw = ImageDraw.Draw(canvas)
    def text(value, xy, width, height, size, color=INK):
        text_box(draw,value,xy,width,height,size,fill=color,font_path=KOREAN_FONT)
    text('성공 경험을 메모리로 전달한다면?', (40,28),1840,75,48)
    draw.rounded_rectangle((38,112,1882,207),radius=15,fill='#fff1de',outline=ORANGE,width=2)
    text('설명용 재구성 · 실제 에이전트 발화 아님', (64,134),1780,58,39,ORANGE)
    draw.rounded_rectangle((38,235,943,920),radius=18,fill='white',outline='#d5e2ed',width=2)
    draw.rounded_rectangle((973,235,1882,920),radius=18,fill='white',outline='#d5e2ed',width=2)
    text('01  실제 기록에서 확인한 내용', (66,264),845,60,34,TEAL)
    text(f"초기 상태 {probe['init_state_id']} · 고정된 OpenVLA\n작성된 지시문으로 {probe['step_index']} actions 후 성공\n성공 판정: LIBERO 환경 기록", (66,349),840,195,35)
    text('실제로 전달한 전체 지시', (66,586),840,45,25,MUTED)
    text(probe['schedule'][0]['instruction'],(66,649),838,143,34)
    text('이 성공 실행의 Agent API 호출: 0회', (66,848),840,44,28,TEAL)
    text('02  Memory Retrieval 전달 예시', (1001,264),840,60,34,ORANGE)
    text(HANDOFF,(1001,365),838,322,38)
    text('경험 검색 → 목표·관측 비교 → 실행 후보 전달', (1001,740),830,100,31,ORANGE)
    text('이 문장은 구조를 설명하기 위해 작성한 예시입니다.',(1001,848),830,45,25,MUTED)
    text('다음 영상: 실제 baseline 실패 ↔ 지시문 보정 성공. 자동 메모리 검색 성공을 보여주는 영상은 아닙니다.',(42,949),1834,57,27)
    text('실제 source attempt: '+probe['attempt_id'],(42,1016),1834,37,20,MUTED)
    return canvas


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--probe-attempt',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--language',choices=['ko','en'],default='ko')
    args=parser.parse_args()
    if args.input.resolve()==args.output.resolve():
        raise ValueError('Preserve the original recording')
    probe=json.loads(args.probe_attempt.read_text())
    if (probe['condition'],probe['provenance'],probe['outcome'],probe['agent_api_calls']) != ('diagnostic_instruction_probe','real_execution','success',0):
        raise ValueError('Expected the real zero-agent-call successful calibration record')
    source=json.loads(args.input.with_suffix('.json').read_text())
    if source['output_sha256']!=sha256(args.input) or source['sides']['instruction_calibration']['attempt_id']!=probe['attempt_id']:
        raise ValueError('Source movie provenance mismatch')
    card=english_explanation_card(probe) if args.language=='en' else explanation_card(probe)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    card.save(args.output.with_name(args.output.stem+'-intro.png'))
    reader=imageio_ffmpeg.read_frames(str(args.input),pix_fmt='rgb24'); media=next(reader)
    if media['fps']!=20 or tuple(media['size'])!=(1920,1080):
        raise ValueError('Unexpected source format')
    writer=imageio_ffmpeg.write_frames(str(args.output),(1920,1080),fps=20,codec='libx264',quality=8,
        macro_block_size=1,output_params=['-movflags','+faststart'],ffmpeg_log_level='warning')
    writer.send(None); recorded=0
    try:
        for _ in range(200):writer.send(card.tobytes())
        for frame in reader:
            writer.send(frame);recorded+=1
    finally:
        writer.close()
    if recorded!=source['frame_count']:
        raise ValueError('Source movie frame count differs from provenance')
    result={'schema_version':'1','comparison':'explained_direct_instruction_calibration',
        'source_video':str(args.input.resolve()),'source_video_sha256':sha256(args.input),
        'source_provenance':source,'explanation_is_actual_agent_utterance':False,'agent_retrieval_shown':False,
        'language':args.language,
        'explanation_label':('Illustrative explanation · not an actual agent utterance' if args.language=='en' else '설명용 재구성 · 실제 에이전트 발화 아님'),
        'illustrative_handoff':EN_HANDOFF if args.language=='en' else HANDOFF,
        'facts_source':str(args.probe_attempt.resolve()),'facts_source_sha256':sha256(args.probe_attempt),
        'intro_seconds':10,'intro_frame_count':200,'recorded_replay_frame_count':recorded,
        'fps':20,'frame_count':200+recorded,'duration_s':(200+recorded)/20,'output_sha256':sha256(args.output),
        'time_basis':'Ten-second static explanation precedes the unchanged sequence of decoded source replay frames; no extra robot motion.'}
    args.output.with_suffix('.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'output':str(args.output.resolve()),'frame_count':result['frame_count'],'sha256':result['output_sha256']}))


if __name__=='__main__':main()
