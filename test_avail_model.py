# check_multi.py
import asyncio
import edge_tts

async def main():
    voices = await edge_tts.list_voices()
    multi = [v for v in voices if 'Multilingual' in v['ShortName']]
    print(f"다국어(Multilingual) 모델: {len(multi)}개")
    print("-" * 70)
    for v in multi:
        name = v['ShortName']
        gender = v['Gender']
        locale = v['Locale']
        print(f"{name:<50} {gender:<8} {locale}")

    # 한국어 읽기 테스트할 후보
    candidates = [v['ShortName'] for v in multi]
    test_text = "천하를 호령했던 매화검존 청명이 환생했다."
    print(f"\n한국어 테스트: '{test_text}'")
    print("-" * 70)
    
    for c in candidates[:10]:
        try:
            comm = edge_tts.Communicate(text=test_text, voice=c)
            data = b''
            async for chunk in comm.stream():
                if chunk['type'] == 'audio':
                    data += chunk['data']
            status = f"OK ({len(data):,}B)" if len(data) > 1000 else f"TOO_SMALL ({len(data)}B)"
        except Exception as e:
            status = f"ERROR: {e}"
        print(f"  {c:<50} {status}")

asyncio.run(main())
