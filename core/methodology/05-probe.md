## 시작 전 — 이 환경에서 무엇이 되는지 확인한다

같은 스킬이 Claude Code·Claude 앱·Codex·ChatGPT for Work에서 함께 돈다. 되는 일이
환경마다 다르므로 **넘겨짚지 말고 실제로 해 보고 확인한다.** 조직 설정이나 샌드박스
정책이 문서에 적힌 것과 다를 수 있어서, 미리 정해 둔 답보다 지금 해 본 결과가 정확하다.

```python
import sys; sys.path.insert(0, "scripts")   # SKILL.md 옆의 scripts 폴더
from refver.__main__ import main
main(["probe"])
```

셸을 쓸 수 있으면 `python3 -m refver probe` 한 줄로도 된다.

확인할 세 가지와, 안 될 때의 대처.

| 확인 | 안 되면 |
|---|---|
| PDF 판독기(pymupdf·pdfminer·pypdf·pdftotext 중 하나) | 2단계를 원문으로 확인할 수 없다. 사용자에게 알리고 텍스트로 받는다 |
| 코드에서 인터넷 접근 | 원문을 스스로 못 받는다 → 아래 '원문을 못 받아 오는 환경' 절차 |
| 독립 에이전트 실행 | 3단계 재검증을 눈감기 패스로 한다 |

**코드가 인터넷에 나갈 수 없는 환경이 있다**(ChatGPT for Work의 코드 실행 등).
그때는 URL을 받아 오려다 실패하고 나서 포기하지 말고, 0단계를 마친 뒤
**필요한 원문 목록을 한 번에** 사용자에게 요청한다 — 출처명, 알고 있는 URL,
그 출처에 걸린 인용 번호를 함께 적어 무엇을 왜 올려야 하는지 알게 한다.
올라오지 않은 출처는 2단계를 `INSUFFICIENT_EVIDENCE`로 남긴다.
서지 실존 확인(1단계)은 모델의 웹 검색으로 대체로 가능하니 거기까지는 해 둔다.

확인 결과를 리포트의 `run.capabilities_observed`에 적고, 제약이 있었으면
`run.degraded`와 `run.degraded_reasons`를 채운다. **무엇을 못 했는지 밝히지 않은
리포트는 무엇을 했는지도 믿을 수 없다.**
