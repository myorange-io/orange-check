# reference-verification

이미 작성된 문서(보고서·논평·제안서·docx/pdf)의 **참고문헌과 인용을 검증**하는 Claude 스킬입니다.

핵심은 검증을 **두 단계로 분리**하는 것입니다.

1. **서지 실존/정확성** — 그 출처가 실제로 존재하고 서지정보(저자·연도·제목·권호·URL)가 맞는가?
2. **인용 적절성** — 본문이 인용한 주장을 그 출처가 **실제로 뒷받침**하는가? 논리적으로 타당한 인용인가?

> **출처가 존재한다 ≠ 그 출처가 본문 주장을 뒷받침한다.**
> 서지만 보면 통과처럼 보이는 문서도, 인용 적절성을 따지면 과확장·변수명 오기·자료원 불일치가 드러납니다. 실제 검증의 대부분은 2단계에서 일어납니다.

검증은 **원문 PDF를 직접 판독**하고(요약·스니펫 추측 금지), 근거를 **페이지·행 번호까지 핀포인트**하며, 판정을 **독립적으로 재검증**(CoVe)해 오판을 막고, 부적합 인용에는 **더 적합한 대체 출처**를 제시합니다.

---

## 두 가지 변형

같은 방법론을, 실행 환경에 맞춰 두 가지로 제공합니다.

| 폴더 | 대상 | 실행 전제 |
|------|------|-----------|
| [`cowork/`](cowork/) | **Claude 앱 (Cowork)** | 코드 실행 샌드박스(Python)·웹 검색·파일 업로드/다운로드. `pip install pymupdf requests` |
| [`claude-code/`](claude-code/) | **Claude Code (CLI)** | 로컬 셸(Bash)·`pdftotext`/PyMuPDF·`curl`·WebSearch/WebFetch·서브에이전트 |

차이는 **런타임 전제**뿐, 검증 방법론(0~5단계)은 동일합니다.

```
reference-verification/
├── README.md
├── cowork/
│   ├── SKILL.md
│   └── references/pdf-and-deeplink-retrieval.md
└── claude-code/
    ├── SKILL.md
    └── references/pdf-and-deeplink-retrieval.md
```

---

## Cowork에서 사용하기

### 1) 스킬 설치

이 저장소를 받습니다.

```bash
git clone https://github.com/myorange-io/reference-verification.git
```

`cowork/` 폴더가 하나의 스킬입니다(`SKILL.md` + `references/`). Claude 앱에 스킬로 등록합니다.

- **Claude 앱(데스크톱/웹)**: **설정 → Capabilities/스킬** 에서 스킬을 추가합니다. 업로드가 필요한 경우 `cowork/` 폴더를 zip으로 묶어 올립니다.
  ```bash
  cd reference-verification && zip -r reference-verification-cowork.zip cowork
  ```
- **조직(myorange-io) 공용**: 워크스페이스 관리자가 스킬을 등록하면 팀원 모두가 사용할 수 있습니다.

> 메뉴 명칭은 플랜·버전에 따라 다를 수 있습니다. 핵심은 `SKILL.md`가 들어 있는 `cowork/` 폴더를 "스킬"로 인식시키는 것입니다.

### 2) 사용

1. 새 대화에서 **검증할 문서(.docx 또는 .pdf)를 첨부**합니다.
2. 이렇게 요청합니다:
   - "이 문서의 **참고문헌 검증**해줘"
   - "각 인용이 출처에 맞게 인용됐는지, 논리적으로 타당한지도 봐줘"
   - (선택) "리포트를 **docx로** 저장해줘"
3. Claude가 0~5단계를 수행하고, **검증 리포트 파일을 다운로드 링크로 제공**합니다.

스킬은 `SKILL.md`의 트리거 문구("참고문헌 검증", "레퍼런스 검증", "인용 검증", "출처 검증" 등)에 자동 발동합니다.

### 3) 결과물

검증 리포트(.md 기본, 요청 시 .docx)에는 다음이 담깁니다.

- 종합 판정 — 서지 PASS/FAIL 집계, 인용 적절성 뒷받침/부분/안됨 집계
- **1단계 서지 검증표** — 출처별 PASS/MISMATCH/FAIL, 등급(T1~T5), 1차 출처 URL·딥링크
- **2단계 인용 적절성 검증표** — 본문 인용 위치 ↔ **출처 페이지·행** ↔ 판정
- 수치 재검증(합계·비율·단위)
- **대체/보강 레퍼런스**(URL·등급·근거)
- 사람 검토 필요 체크리스트

---

## Claude Code에서 사용하기

`claude-code/` 폴더를 개인/프로젝트 스킬 경로에 둡니다.

```bash
# 개인 전역 스킬
mkdir -p ~/.claude/skills/reference-verification
cp -R claude-code/* ~/.claude/skills/reference-verification/

# 또는 프로젝트 스킬
mkdir -p .claude/skills/reference-verification
cp -R claude-code/* .claude/skills/reference-verification/
```

이후 Claude Code에서 "이 docx 참고문헌 검증해줘"처럼 요청하면 발동합니다.

---

## 방법론 (0~5단계)

| 단계 | 내용 |
|------|------|
| 0. 인용 수집 | 본문·각주·미주·하이퍼링크 전수 추출. 1·2단계 **동일 번호** 부여 |
| 1. 서지 실존 | 웹검색·학술DB·공식DB로 실존 확인 → PASS/MISMATCH/FAIL, 5등급 분류 |
| 2. 인용 적절성 | **원문 PDF 직접 판독 + 페이지·행 핀포인트** → 뒷받침/부분/안됨 |
| 3. 독립 재검증 | 사전 결론 없이 백지 재판정(CoVe). 원문을 연 쪽이 이긴다 |
| 4. 대체 출처 | 부적합 인용에 더 적합한 T1~T3 출처 제시(URL 확인분만) |
| 5. 리포트 | 검증표·수치 재검증·대체 출처·체크리스트를 파일로 산출 |

자주 잡히는 부적절 인용 패턴: **과확장**, **변수명 오기**(가구소득↔처분가능소득), **자료원 불일치**(소득 4분위↔의료급여·차상위), **방향성만 맞음**. 변수명·자료원은 반드시 **1차 PDF**로 확인합니다(요약·언론은 표현을 바꿉니다).

PDF 판독·JS로 가려진 정부 보도자료 다운로드·딥링크 보완 기법은 각 변형의 `references/pdf-and-deeplink-retrieval.md`에 정리돼 있습니다.

---

## 라이선스

myorange-io 내부 사용. (별도 표기 전까지 사내 도구)
