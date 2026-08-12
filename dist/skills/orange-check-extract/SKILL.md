---
name: orange-check-extract
description: "문서(docx·pdf·hwp·hwpx)에서 인용을 전수 추출해 citations.json으로 만든다. 본문뿐 아니라 각주·미주·하이퍼링크까지 빠짐없이 훑어 \"본문 주장 ↔ 인용 출처\" 쌍으로 정리한다. 인용 목록 뽑기, 참고문헌 정리, 각주 추출 요청에 쓴다."
license: MIT
metadata:
  runtime-profile: universal
  suite: orange-check
  contract: refver-report/1.0
---

# Orange Check — 인용 수집

검증 파이프라인의 입구. **여기서 놓친 인용은 뒤의 어떤 단계도 검증하지 못한다.**
그래서 이 스킬의 목표는 판정이 아니라 **누락 0건**이다.

> 실행 환경: Claude Code · Claude 앱(Cowork) · OpenAI Codex · ChatGPT for Work

---

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

---

## 0단계 — 인용 전수 수집

여기서 놓친 인용은 영원히 검증되지 않는다. 참고문헌 목록만 보면 안 된다. 실제 문서에서
인용의 상당수는 **각주·미주에만** 있고 목록에는 없다.

```python
import sys; sys.path.insert(0, "scripts")
from refver.doc import read_document, summarize
units = read_document("문서.docx")
print(summarize(units))          # {'body': 43, 'footnote': 4, 'endnote': 4}
```

셸이 있으면 `python3 -m refver read <문서> --summary` 로도 된다.

지원 형식: `.docx` `.pdf` `.hwp` `.hwpx` `.txt` `.md`.
한글 문서는 의존성 없이 읽는다. HWPX는 각주·미주까지 분리되고, HWP 5.x 이진 파일은
본문이 온전히 나오되 각주 귀속은 근사다. 각주가 중요한 HWP라면 HWPX로 저장하거나
`rhwp`가 있으면 `read --via-pdf`로 PDF를 거쳐 쪽·행까지 얻는다.

수집한 뒤 할 일.

- 인용마다 **"본문 주장 ↔ 인용 출처"** 쌍으로 정리하고 번호를 매긴다.
- 번호는 1단계와 2단계가 **같은 번호**를 쓴다. 본문 등장 위치는 별도 칸에 적는다.
- `claim`에는 문서의 문장을 **그대로 옮긴다.** 요약하지 않는다 — 나중에 대조가 불가능해진다.
- 기관 내부 자료(제공받은 PPT·원자료 등)는 외부 검증 대상에서 빼되 "내부 자료로 분류"라고 명시한다.

---

## 참고 문서

- `references/ref-report-contract.md` — 리포트 계약 (report.json)

## 산출물

`citations.json` — 리포트 계약의 `citations` 배열과 같은 모양이되 `stage1`·`stage2`는 비운다.

```json
{"schema_version": "refver-report/1.0",
 "document": {"filename": "제안서.docx", "format": "docx"},
 "citations": [{"id": "C01", "claim": "문서의 문장 그대로", "doc_locator": "footnote:3",
                "cited_source": {"authors": "", "year": "", "title": ""}}]}
```

## 스스로 점검할 것

- 각주·미주에만 있는 인용을 넣었는가? 참고문헌 목록만 보면 반드시 놓친다
- `claim`이 문서의 문장 그대로인가? 요약했다면 다시 옮긴다
- 같은 출처를 여러 번 인용했다면 **주장마다** 따로 번호를 매겼는가
- 추출 건수가 문서의 각주·미주 개수와 맞는가
