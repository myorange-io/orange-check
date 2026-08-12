## 6단계 — 리포트 산출

**두 파일을 낸다.**

- `report.json` — 기계가 읽는 정본. 모델이 직접 작성한다
- `참고문헌_검증리포트.md` — 사람이 읽는 리포트. **report.json에서 생성한다**

<!--if:shell-->
```bash
python3 {{TOOLKIT}} validate report.json
python3 {{TOOLKIT}} render report.json -o 참고문헌_검증리포트.md
```
<!--endif-->
<!--if:python_only-->
```python
from refver.report import load, validate, render
rep = load("report.json"); assert not validate(rep)
open("참고문헌_검증리포트.md","w",encoding="utf-8").write(render(rep))
```
<!--endif-->

마크다운을 손으로 쓰지 않는다. 두 벌을 따로 쓰면 반드시 어긋나고, 어긋난 순간
어느 쪽이 진실인지 알 수 없게 된다.

리포트 구성은 렌더러가 정한다: 검증 개요 · 종합 판정 · 1단계 표 · 2단계 표 ·
문제 인용 상세(슬롯 표·근거 인용·대체 출처) · 사람이 확인할 항목.

표기 규칙.
- 기관은 **현행 명칭 + 도메인 병기** — 예: `성평등가족부(mogef.go.kr)`
- 1·2단계는 **같은 번호**를 쓴다
- (FAIL + MISMATCH + NOT_SUPPORTED + PARTIAL) ÷ 전체 > 30%면 근거 전면 재작성을 권고한다
