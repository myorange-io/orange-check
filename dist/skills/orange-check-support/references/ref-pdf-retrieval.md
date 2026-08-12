# 원문 PDF·딥링크 취득 실전 기법 (Claude Code)

2단계(인용 적절성)는 **원문을 직접 읽어야** 한다. WebFetch가 막히는 흔한 상황별 해법.

## 1. WebFetch가 "PDF 판독 불가/바이너리"라고 할 때

WebFetch는 작은 요약 모델로 변환한다. 텍스트 PDF인데도 실패하는 경우가 많다. **포기하지 말고 직접 추출**한다.

```bash
pdftotext -layout source.pdf -    # poppler
```

```python
import fitz  # PyMuPDF
d = fitz.open('source.pdf')
print('pages:', d.page_count)
for i in range(d.page_count):
    t = d[i].get_text()
    for ln, line in enumerate(t.split('\n'), 1):
        if line.strip() and any(k in line for k in KEYWORDS):
            print(f'p{i+1} l{ln}: {line.strip()}')   # 페이지·행 핀포인트
```

- 키워드 전수검색으로 **존재/부재** 모두 증거화(부재 = 0회 → 과확장 판정 근거).
- 한글 PDF도 대부분 텍스트 레이어가 있어 추출된다. 진짜 스캔본(이미지)만 OCR 필요.

## 2. JavaScript로 가려진 정부/기관 다운로드

보도자료·보고서가 `fn_fileDownload('id','seq')` 같은 JS 핸들러로만 걸려 직접 URL이 없을 때.

```bash
# (1) 원본 HTML을 받아 다운로드 폼/파라미터를 찾는다
curl -sL -k -A "Mozilla/5.0" "PAGE_URL" -o page.html
grep -oiE "onclick=\"[^\"]*[Dd]ownload[^\"]*\"" page.html   # fn_fileDownload('710060','1') 등
python3 -c "import re;h=open('page.html',encoding='utf-8',errors='ignore').read();m=re.search(r'<form[^>]*down[^>]*>.*?</form>',h,re.S|re.I);print(m.group(0)[:800] if m else 'no form')"

# (2) 세션 쿠키 확보 후, 폼의 모든 hidden 필드를 포함해 POST
curl -sL -k -c cookies.txt -A "Mozilla/5.0" "PAGE_URL" -o /dev/null
curl -sL -k -b cookies.txt -A "Mozilla/5.0" --referer "PAGE_URL" \
  --data "bbid=...&bbtSn=...&atfileSn=ID&atfileSeq=SEQ&fileDir=&fileName=" \
  "https://HOST/DOWNLOAD_ENDPOINT" -o file.bin -w "%{http_code} %{content_type}\n"
file file.bin   # PDF인지 확인
```

함정: hidden 필드(`bbid`, `bbtSn` 등)를 빠뜨리면 "파일정보가 없습니다" alert(HTML 129b)가 돌아온다. **폼의 hidden 필드를 전부** 넘길 것. seq를 1~N으로 돌려 첨부 전체를 받아 PDF만 골라낸다.

## 3. 학술 논문 원문 접근

- KoreaMed Synapse: 검색결과의 PDF가 직접 다운로드되는 경우가 많다(`/upload/SynapseData/PDFData/...jkaoh-38-17.pdf`).
- 접근 안 되면 KCI(`kci.go.kr`)·DBpia(`dbpia.co.kr`) 서지·초록으로 권/호/페이지/결론 확인.
- 권·호·연도는 학술지 권 번호로 교차확인(예: 대한구강보건학회지 vol 38 = 2014).

## 4. 딥링크 보완

본문이 홈페이지 URL(예: `knhanes.kdca.go.kr`)만 달았다면, 해당 통계/지표의 **실제 상세 페이지 URL**을 찾아 제시한다.

- KOSIS 통계표: `kosis.kr/statHtml/statHtml.do?orgId=...&tblId=...`
- 질병관리청 대국민시각화 지표상세: `chs.kdca.go.kr/cdhs/biz/pblcVis/details.do?ctgrSn=...`
- 정부 보도자료: 게시판 `list_no`/`bbtSn` 포함 view URL.

딥링크는 직접 열어 **그 지표/표가 맞는지, 자료원이 무엇인지** 확인한 뒤에만 리포트에 싣는다.

## 5. 출처 간 충돌 해소

요약 페이지·언론 보도와 1차 보도자료가 표현이 다를 때(예: '가구소득' vs '처분가능소득'):
- **1차 출처 원문(보도자료/보고서 PDF)이 최종 판정 기준.** 요약·언론은 표현을 바꾸므로 신뢰 순위가 낮다.
- 충돌을 리포트에 명시하되, 최종 판정은 원문 표현을 따른다.
