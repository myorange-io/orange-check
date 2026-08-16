## 6단계 — 리포트 산출

**판단만 적고 나머지는 조립기가 만든다.** 리포트를 통째로 받아쓰면 60,000자를 쓰게 되는데,
그중 모델만 알 수 있는 것은 절반이 안 된다. 주장 원문과 서지는 0단계가 이미 가지고 있고,
판정과 오류 유형은 슬롯 표에서 규칙대로 나오며, 근거 인용문은 쪽·행만 알면 원문에서
뽑힌다. 받아쓰면 시간만 드는 것이 아니라 **틀릴 자리가 생긴다.**

```bash
python3 -m refver assemble judgment.json --citations citations.json \
    --corpus <출처폴더> --document <원문서> -o report.json
```

판단 파일의 계약은 바로 앞 절에 있다.

### 사람이 읽는 리포트

```python
from refver.report import load, validate, render
rep = load("report.json"); assert not validate(rep)
open("참고문헌_검증리포트.md","w",encoding="utf-8").write(render(rep))
```

마크다운을 손으로 쓰지 않는다. 두 벌을 따로 쓰면 반드시 어긋나고, 어긋난 순간
어느 쪽이 진실인지 알 수 없게 된다.

리포트 구성은 렌더러가 정한다: 검증 개요 · 종합 판정 · 1단계 표 · 2단계 표 ·
문제 인용 상세(슬롯 표·근거 인용·대체 출처) · 사람이 확인할 항목.

표기 규칙.
- 기관은 **현행 명칭 + 도메인 병기** — 예: `성평등가족부(mogef.go.kr)`
- 1·2단계는 **같은 번호**를 쓴다
- (FAIL + MISMATCH + NOT_SUPPORTED + PARTIAL) ÷ 전체 > 30%면 근거 전면 재작성을 권고한다
