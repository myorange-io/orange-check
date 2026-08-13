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

**각주·미주가 어느 문장에 달렸는지 확인한다.** 추출 결과에서 노트는 본문과 따로 나오므로,
그냥 보면 문단 끝에 달린 것처럼 보인다. 실제로는 문단 첫 문장에 달린 각주가 흔하고,
그걸 놓치면 그 인용은 통째로 빠진다. 본문 단위의 `meta.notes`에 노트가 문단의 몇 번째
글자 뒤에 붙었는지(`after_chars`) 들어 있으니, 그 앞 문장을 주장으로 잡는다.

```python
for u in units:
    for n in u.meta.get("notes", []):
        print(n["kind"], n["id"], "→", u.text[:n["after_chars"]][-40:])
```

수집한 뒤 할 일.

- 인용마다 **"본문 주장 ↔ 인용 출처"** 쌍으로 정리하고 번호를 매긴다.
- 번호는 1단계와 2단계가 **같은 번호**를 쓴다. 본문 등장 위치는 별도 칸에 적는다.
- `claim`에는 문서의 문장을 **그대로 옮긴다.** 요약하지 않는다 — 나중에 대조가 불가능해진다.
- 기관 내부 자료(제공받은 PPT·원자료 등)는 외부 검증 대상에서 빼되 "내부 자료로 분류"라고 명시한다.
