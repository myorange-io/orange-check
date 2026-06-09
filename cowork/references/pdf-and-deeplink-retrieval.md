# 원문 PDF·딥링크 취득 실전 기법 (Cowork)

2단계(인용 적절성)는 **원문을 직접 읽어야** 한다. Cowork 샌드박스(Python)에서의 해법.

준비: `pip install pymupdf requests`. (`poppler`/`pdftotext`는 샌드박스에 없을 수 있으니 **PyMuPDF 우선**)

## 1. PDF 텍스트를 페이지·행 단위로 추출

검색 스니펫·초록만 보고 판정하지 말 것. 원문을 연다.

```python
import requests, fitz
url = "https://.../source.pdf"
open('source.pdf','wb').write(requests.get(url, headers={'User-Agent':'Mozilla/5.0'}, timeout=60, verify=False).content)

d = fitz.open('source.pdf')
print('pages:', d.page_count)
KEYWORDS = ['한부모','저소득','처분가능소득']
for i in range(d.page_count):
    for ln, line in enumerate(d[i].get_text().split('\n'), 1):
        if line.strip() and any(k in line for k in KEYWORDS):
            print(f'p{i+1} l{ln}: {line.strip()}')   # 페이지·행 핀포인트
```

- 키워드 전수검색으로 **존재/부재** 모두 증거화(부재 = 0회 → 과확장 판정 근거).
- 한글 PDF도 대부분 텍스트 레이어가 있어 추출된다. 진짜 스캔본(이미지)만 OCR 필요.

## 2. JavaScript로 가려진 정부/기관 다운로드

보도자료·보고서가 `fn_fileDownload('id','seq')` 같은 JS 핸들러로만 걸려 직접 URL이 없을 때, `requests.Session`으로 폼을 그대로 재현한다.

```python
import requests, re
s = requests.Session(); s.headers['User-Agent'] = 'Mozilla/5.0'
PAGE = "https://www.example.go.kr/board/view.do?bbtSn=710445"
html = s.get(PAGE, verify=False).text

# (1) 다운로드 onclick·폼 hidden 필드 찾기
print(re.findall(r"onclick=\"[^\"]*[Dd]ownload[^\"]*\"", html)[:5])     # fn_fileDownload('710060','1')
print(re.search(r"<form[^>]*down[^>]*>.*?</form>", html, re.S|re.I).group(0)[:800])

# (2) 폼의 모든 hidden 필드를 포함해 POST (seq를 1..N 순회)
for seq in range(1, 5):
    r = s.post("https://www.example.go.kr/board/down.do",
               data={'bbid':'news405','bbtSn':'710445','atfileSn':'710060',
                     'atfileSeq':str(seq),'fileDir':'','fileName':''},
               headers={'Referer': PAGE}, verify=False)
    open(f'f{seq}.bin','wb').write(r.content)
    print(seq, len(r.content), r.headers.get('content-type'))   # PDF/zip(hwp) 구분
```

함정: hidden 필드(`bbid`, `bbtSn` 등)를 빠뜨리면 "파일정보가 없습니다" 같은 짧은 HTML(수백 바이트)이 돌아온다. **폼의 hidden 필드를 전부** 넘길 것. 받은 바이트가 PDF인지 `b[:4]==b'%PDF'`로 확인하고, hwpx(zip)는 별도 처리.

## 3. 학술 논문 원문 접근

- KoreaMed Synapse: 검색결과의 PDF가 직접 다운로드되는 경우가 많다(`/upload/SynapseData/PDFData/...`).
- 접근 안 되면 KCI(`kci.go.kr`)·DBpia(`dbpia.co.kr`) 서지·초록으로 권/호/페이지/결론 확인.
- 권·호·연도는 학술지 권 번호로 교차확인.

## 4. 딥링크 보완

본문이 홈페이지 URL만 달았다면, 해당 통계/지표의 **실제 상세 페이지 URL**을 웹 검색으로 찾아 제시한다.

- KOSIS 통계표: `kosis.kr/statHtml/statHtml.do?orgId=...&tblId=...`
- 질병관리청 대국민시각화 지표상세: `chs.kdca.go.kr/cdhs/biz/pblcVis/details.do?ctgrSn=...`
- 정부 보도자료: 게시판 `list_no`/`bbtSn` 포함 view URL.

딥링크는 직접 열어 **그 지표/표가 맞는지, 자료원이 무엇인지** 확인한 뒤에만 리포트에 싣는다.

## 5. 출처 간 충돌 해소

요약 페이지·언론과 1차 보도자료의 표현이 다를 때(예: '가구소득' vs '처분가능소득'):
- **1차 출처 원문(보도자료/보고서 PDF)이 최종 판정 기준.** 요약·언론은 표현을 바꾸므로 신뢰 순위가 낮다.
- 충돌을 리포트에 명시하되, 최종 판정은 원문 표현을 따른다.
