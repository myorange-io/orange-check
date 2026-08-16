# 리포트 계약 (report.json)

기계가 읽는 정본. 사람용 마크다운은 이 파일에서 생성한다.

```json
{
  "schema_version": "refver-report/1.0",
  "run": {
    "platform_profile": "claude-code | claude-app | codex | chatgpt-work",
    "capabilities_observed": {"pdf_backend": "pymupdf", "net_scripts": false, "subagents": true},
    "degraded": false,
    "degraded_reasons": [],
    "generated_at": "2026-08-13T04:39:55+00:00"
  },
  "document": {"filename": "제안서.docx", "format": "docx"},
  "citations": [
    {
      "id": "C01",
      "claim": "문서에 적힌 문장 그대로. 요약하지 않는다.",
      "doc_locator": "body:12 | footnote:3 | endnote:1",
      // 각주 표시가 문단 중간에 달렸으면 둘 다 적는다 — "body:5 · footnote:1"
      "cited_source": {
        "authors": "", "year": "", "title": "", "publisher": "",
        "journal": "", "volume": "", "issue": "", "pages": "", "series": "", "url": "",
        "date": ""
      },
      "stage1": {
        "verdict": "PASS | MISMATCH | FAIL | UNVERIFIABLE",
        "tier": "T1 | T2 | T3 | T4 | T5 | null",
        "matched_source_id": "실제로 찾아낸 출처 식별자 또는 null",
        "mismatch_fields": ["year"],
        "note": ""
      },
      "stage2": {
        "verdict": "SUPPORTED | PARTIAL | NOT_SUPPORTED | NOT_APPLICABLE | INSUFFICIENT_EVIDENCE",
        "pattern": "none | hallucinated | biblio_mismatch | overreach | variable_name | wrong_dataset | number_error | time_mismatch | direction_only | unsupported | tier_violation",
        "slots": {
          "who":     {"claimed": "저소득 한부모 여성", "source": "한부모가족 전체", "match": false},
          "when":    {"claimed": "2024년", "source": "2024년", "match": true},
          "what":    {"claimed": "양육비 미수령 비율", "source": "양육비 미수령 비율", "match": true},
          "value":   {"claimed": "72.1%", "source": "72.1%", "match": true},
          "dataset": {"claimed": "한부모가족 실태조사", "source": "한부모가족 실태조사", "match": true},
          "relation": null
        },
        "evidence": [
          {"source_id": "S01", "page": 2, "line": 14,
           "quote": "출처 원문에 적힌 문장 그대로"}
        ],
        "absence_checked": ["저소득", "여성 가구주"],
        "note": ""
      },
      "tier_violation": false,
      "replacement": {
        "action": "replace | fix_claim | fix_biblio | delete | none_found",
        "citation": "기관, 연도, 제목", "tier": "T1",
        "url": "실제로 열어 본 URL", "supports": "이 출처의 어느 문장이 주장을 뒷받침하는가"
      }
    }
  ]
}
```

## 반드시 지킬 것

- `claim`은 **문서의 문장을 그대로** 옮긴다. 요약하면 나중에 어느 문장에 대한 판정인지 대조할 수 없다.
- `evidence[].quote`는 **출처 원문 표현 그대로**. 이것이 근거의 본체다.
- `page`는 정수. `line`은 참고값이다 — PDF 판독기마다 줄 나눔이 달라 값이 달라진다.
- `SUPPORTED`·`PARTIAL`이면 `evidence`가 비면 안 된다.
- `PARTIAL`이면 `slots`에 어느 칸이 어긋났는지 있어야 한다.
- `MISMATCH`면 `mismatch_fields`가 있어야 한다.
- 원문을 못 구했으면 `INSUFFICIENT_EVIDENCE`. 그럴듯한 판정을 지어내지 않는다.
- `id`는 1단계와 2단계가 같은 번호를 쓴다.
- 문제 인용에는 `replacement.action`으로 무엇을 하라는 것인지 밝힌다.
- `absence_checked`는 **출처에서 0회로 확인된 검색어만** 담는다. `["치주질환", "치주",
  "잇몸"]` 처럼 적고, 설명은 `note`에 쓴다. 그중 최소 하나는 **본문 주장이 실제로 쓴
  말**이어야 한다. 세어 보지 않은 말이나 한 번이라도 나오는 말을 적으면 `audit`이
  치명으로 잡는다.

`validate` 명령이 위 규칙을 기계로 검사한다. 통과하기 전에는 리포트를 내지 않는다.
