# ⚔️ 무협 팩토리 (Murim Factory)

무협 웹툰 다국어 유튜브 자동화 마스터 컨트롤 UI

## 기능
- 🔍 **트렌드 스카우트** — 무협 웹툰 트렌드 AI 분석 (Claude Haiku 4.5)
- ✍️ **스크립트 공장** — 리캡 대본 자동 생성 + 다국어 번역
- 🎨 **미디어 공장** — 이미지 프롬프트 추출 (Midjourney/ElevenLabs 연동 예정)
- 📺 **채널 관리** — 4개국 채널 업로드 스케줄링
- 💰 **비용 트래커** — API 사용량 실시간 모니터링

## 실행 방법

### 로컬 실행
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # API 키 입력
python main.py
# → http://localhost:8080
우선 현재 상태를 