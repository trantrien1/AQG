# Pipeline Multi-Agent — Quy trình xử lý một tài liệu PDF

Tài liệu mô tả toàn bộ đường đi của một file PDF trong hệ thống: từ lúc người
dùng chọn file đến lúc câu hỏi được duyệt và đưa vào ngân hàng câu hỏi.

```
Người dùng chọn PDF
      │
      ▼
①  CHUẨN BỊ (chạy ngầm ngay khi chọn file)
      kiểm định PDF → đóng gói tài liệu → trích dàn ý gợi ý cấu hình
      │
      ▼   người dùng chọn cấu hình rồi bấm Generate
②  SINH CÂU HỎI (Orchestrator điều phối, 3 câu chạy đồng thời)
      mỗi câu đi qua:  Writer → Distractor → Verifier → Critic → Formatter
      │
      ▼
③  HẬU XỬ LÝ
      kiểm chứng nhãn chuẩn đầu ra → lưu kết quả + danh sách câu bị loại
      │
      ▼
④  NGƯỜI DÙNG DUYỆT
      duyệt từng câu · 👎 sinh lại · sinh thêm · luyện tập · export
      │
      ▼
⑤  NGÂN HÀNG CÂU HỎI
      kiểm tra trùng lặp 3 tầng (embedding ngữ nghĩa) → thêm vào bank
```

---

## ① Chuẩn bị — chạy ngầm ngay khi chọn file

Bắt đầu **trước khi người dùng bấm Generate**, để lúc bấm thì phần việc nặng đã
xong sẵn. Gồm ba bước:

1. **Kiểm định PDF**: đúng định dạng, không quá 20MB, không quá 200 trang.
   Không đạt thì báo lỗi ngay trên form.
2. **Đóng gói tài liệu**: file PDF được encode base64 và đóng gói **nguyên vẹn**
   thành phần đính kèm cho các lần gọi LLM sau này — không render ảnh, không
   OCR, không trích text, không chia nhỏ. Gói này được **cache lại** nên mọi
   agent về sau dùng chung, không phải đóng gói lại. (Hệ thống còn hai chế độ
   dự phòng cho provider không nhận file PDF: gửi dạng file part chuẩn, hoặc
   render từng trang thành ảnh.)
3. **Trích dàn ý**: một lần gọi LLM đọc lướt toàn bộ tài liệu, trả về tên tài
   liệu, 3–8 chủ đề chính, 2–4 **chuẩn đầu ra gợi ý** (kiểu "Tính được…",
   "Vận dụng được…") và số câu hỏi hợp lý cho lượng nội dung. Kết quả hiện
   ngược lên form để người dùng chọn thay vì phải tự nghĩ. Bước này lỗi cũng
   không sao — chỉ mất phần gợi ý.

## ② Sinh câu hỏi — Orchestrator điều phối

Khi người dùng bấm Generate với cấu hình đã chọn (số câu, mức Bloom, độ khó,
chuẩn đầu ra, có/không kèm lời giải), **Orchestrator** nhận nhiệm vụ sinh đủ N
câu đạt chuẩn. Nó làm việc theo nguyên tắc:

### Giao chỉ tiêu cho từng câu trước khi sinh

Mỗi câu hỏi được ấn định sẵn **trước khi gọi LLM**:

- **Mức Bloom** [8] — rải đều theo phân bố yêu cầu (ví dụ đề trộn thì lần lượt
  Nhận biết → Thông hiểu → Vận dụng…), kèm độ khó mục tiêu tương ứng
  (0.30 / 0.50 / 0.70 / 0.85 trên thang 0–1).
- **Một chuẩn đầu ra cụ thể** — luôn chọn chuẩn đầu ra đang được phủ **ít
  câu nhất** (tính cả những câu đang sinh dở), nên danh sách chuẩn đầu ra được
  phủ đều; nếu một câu thất bại giữa chừng, chuẩn đầu ra đó tự động được bù ở
  câu sau.
- **Hồ sơ sở thích** từ phản hồi của người dùng ở các lượt trước (nếu có), và
  danh sách **các câu đã sinh** để cấm lặp lại cùng dạng/số liệu.

### Chạy đồng thời và điều kiện dừng

Ba câu được sinh **đồng thời** (mỗi câu là một chuỗi agent độc lập); phần ghép
kết quả và khử trùng lặp chạy tuần tự nên không đụng độ dữ liệu. Thực đo: ~28
giây/câu khi chạy đồng thời, so với ~51 giây khi tuần tự.

Orchestrator dừng khi: đủ N câu đạt chuẩn; hoặc đã thử quá 2 lần số câu yêu cầu
(+6 dự phòng); hoặc thất bại liên tiếp quá nhiều lần (ngưỡng tỉ lệ theo N) —
tránh chạy mãi khi model đang gặp sự cố.

### Kỹ thuật ở tầng điều phối

- **Sinh–lọc–thử lại (generate-then-filter / rejection sampling)** [1], [2]: không tin
  một lần sinh nào; mỗi câu phải sống sót qua chuỗi kiểm định, rớt thì sinh câu
  mới thay vì sửa chữa (không có agent Refiner — thử lại rẻ và sạch hơn vá).
- **Lập lịch theo hạn ngạch (quota scheduling)**: mức Bloom rải bằng
  *round-robin có trọng số* theo phân bố yêu cầu; chuẩn đầu ra chọn theo
  *least-covered-first* — luôn ưu tiên chuẩn đang được phủ ít câu nhất, kể cả
  câu đang sinh dở, nên phân bố tự cân bằng khi có câu thất bại.
- **Học sở thích trong ngữ cảnh (in-context preference learning, kiểu RLHF
  không huấn luyện)** [3]: phản hồi 👍/👎 được tổng hợp thành hồ sơ sở thích dạng
  văn bản, tiêm thẳng vào prompt các lượt sinh sau.
- **Ràng buộc phủ định (negative prompting)**: danh sách đề các câu đã có đưa
  vào prompt kèm lệnh cấm lặp dạng bài/số liệu.
- **Tiêm chỉ dẫn theo mô-đun (skill injection)**: mỗi agent được nạp bộ chỉ dẫn
  chuyên biệt riêng (viết câu hỏi, bám thang Bloom, soạn biểu thức kiểm chứng,
  bám nguồn, sinh nhiễu, chấm rubric…) thay vì một system prompt khổng lồ dùng chung.

### Chuỗi 5 agent cho mỗi câu hỏi

| # | Agent | Model | Bản chất | Nhiệm vụ |
|---|-------|-------|----------|----------|
| 1 | **Writer** | gpt-4o | LLM đọc PDF | Soạn đề, đáp án, lời giải, trích dẫn nguồn |
| 2 | **Distractor** | gpt-4o | LLM đọc PDF | 3 phương án nhiễu theo lối "chọn lỗi trước" |
| 3a | **Independent Verifier** | gpt-4o-mini, hoặc hội đồng nhiều model khác họ | LLM chỉ đọc ĐỀ BÀI | Giải lại bài toán từ đầu, không thấy đáp án |
| 3b | **Verifier** | — | Tất định (SymPy) | Đối chiếu các nguồn tính toán, ra 1 trong 5 trạng thái |
| 4 | **Critic** | gpt-4o-mini | LLM đọc PDF | Chấm bám nguồn + 6 tiêu chí chất lượng |
| 5 | **Formatter** | — | Tất định | Đóng gói bản ghi cuối, quyết trạng thái duyệt |

**Writer** — đọc trực tiếp tài liệu và soạn **một** câu trắc nghiệm mới (được
khuyến khích đổi số liệu/tình huống so với bài tập có sẵn, cấm chép nguyên
văn). Kết quả gồm: đề bài tự chứa, đáp án đúng ở dạng đóng đẹp như sách giáo
khoa (phân số, căn, bội π — cấm thập phân dài), lời giải từng bước (số bước tối
thiểu tăng theo mức Bloom: 2/3/4/5), một **trích dẫn nguyên văn** 15–250 ký tự
từ tài liệu làm bằng chứng nguồn, và một **biểu thức kiểm chứng** máy đọc được
để Verifier tính lại đáp án.

Kỹ thuật của Writer:

- **Sinh hai giai đoạn (two-stage, theo hướng CoE)** [4]: giai đoạn này chỉ sinh
  *lõi* câu hỏi (đề + đáp án + lời giải), phương án nhiễu để agent sau lo —
  tách vai giúp mỗi lần gọi tập trung một việc, chất lượng từng phần cao hơn
  sinh cả câu một lượt.
- **Suy luận từng bước có kiểm soát (structured chain-of-thought)** [5]: bắt buộc
  trình bày lời giải thành các bước đánh số với số bước tối thiểu theo mức
  Bloom — vừa là lời giải cho học sinh, vừa ép model thực sự giải bài thay vì
  đoán đáp án; nhưng cấm in nháp suy luận lan man ra ngoài output.
- **Bám nguồn bằng trích dẫn nguyên văn (grounded generation / attribution)**:
  buộc model chỉ ra bằng chứng có thật trong tài liệu; trích dẫn này bị kiểm
  tra máy ở khâu sau, bịa là bị bắt.
- **Tự soạn chứng cứ kiểm chứng (verifier-hint authoring, hướng program-aided
  / PAL)** [6], [7]: model phải viết kèm một biểu thức tính toán máy chạy được tương
  đương bài toán — tách "khả năng giải" khỏi "khả năng tự chấm": việc chấm
  giao cho chương trình, không tin model tự nhận đúng.
- **Kiểm soát độ khó hai trục**: trục *số bước suy luận* khống chế bằng ràng
  buộc mức Bloom (Thông hiểu trở lên cấm hỏi định nghĩa chép lại; Vận dụng cao
  phải phối hợp ≥2 kỹ thuật); trục *độ nặng phép tính* khống chế bằng bộ ràng
  buộc leo thang theo độ khó mục tiêu — cấm bộ số kinh điển của dạng bài, mức
  giữa buộc có dữ kiện học sinh phải tự biến đổi mới ra, mức cao nhất buộc ra
  bài chứa tham số / bài ngược / phối hợp kỹ thuật. Không có trục hai, model
  luôn chọn phiên bản số liệu dễ nhất dù đúng mức Bloom.
- **Bám chuẩn đầu ra được gán**: câu hỏi phải kiểm tra đúng kỹ năng của chuẩn
  đầu ra giao cho nó, không lệch sang kỹ năng khác dù cùng chương.

**Distractor** — tạo đúng 3 phương án sai. Kỹ thuật:

- **Sinh nhiễu error-first theo misconception (hướng DiVERT / LookAlike, bản
  prompting không cần huấn luyện)** [9], [10]: đảo ngược thứ tự thông thường — thay vì
  nghĩ ra "một con số trông na ná đáp án", agent phải chọn **một lỗi sai điển
  hình của học sinh trước** (nhầm dấu khi đạo hàm, quên hệ số chuỗi, lấy nhầm
  cận…), **áp lỗi đó vào chính bài toán** để *tính ra* giá trị sai, rồi mới ghi
  thành phương án. Nhờ vậy mỗi phương án nhiễu là một con đường làm sai có
  thật, không phải số ngẫu nhiên — giá trị sư phạm cao hơn hẳn (chọn nhầm nó
  nghĩa là mắc đúng lỗi đó).
- **Truy xuất từ ngân hàng misconception**: hệ thống duy trì sẵn một danh mục
  lỗi sai phổ biến theo chủ đề; mỗi bài được ghép 6 lỗi khớp nội dung nhất đưa
  vào prompt để agent chọn (chọn có seed cố định theo nội dung bài — cùng một
  bài luôn nhận cùng danh sách, tái lập được khi debug/benchmark).
- **Ràng buộc kiểm chứng được**: mỗi phương án bắt buộc kèm *mô tả chuỗi bước
  làm sai* sao cho ai làm đúng theo chuỗi đó sẽ ra đúng giá trị đó — chính mô
  tả này là thứ Critic chấm được ở tiêu chí nhất quán lỗi–giá trị. Ba phương án
  phải dùng ba lỗi khác nhau, cùng dạng/đơn vị với đáp án. Thiếu bất kỳ điều
  kiện nào → câu bị loại ở khâu này.

**Independent Verifier** — một tác nhân riêng giải lại bài toán từ đầu. Nó
**chỉ nhận đề bài**: không thấy đáp án đã chọn, không thấy danh sách phương án,
không thấy lời giải, không thấy biểu thức kiểm chứng của Writer. Nó phải tự lập
biểu thức từ dữ kiện của đề và nộp về; hệ thống tin **giá trị máy tính ra từ
biểu thức đó**, không tin lời tác nhân tự khai. Nếu chính nó tự mâu thuẫn
(biểu thức ra một số, đáp án nó viết ra một số khác) thì kết quả bị coi là
không dứt khoát và không được dùng làm bằng chứng.

Vì sao cần bước này: biểu thức kiểm chứng của Writer do **cùng một tác nhân**
viết ra cùng lúc với lời giải. Khi nó hiểu sai đề một cách nhất quán, biểu thức
mã hoá đúng cách hiểu sai đó, hai bên khớp nhau và câu sai vẫn được xác nhận.
Đợt đo trên 4 tài liệu cho thấy điều này xảy ra thật: trong 4 câu có đáp án sai,
tầng kiểm chứng bắt được 2 và **xác nhận nhầm 2**. Hai thứ đem so không phải hai
*nguồn* độc lập, mà là hai *sản phẩm* của một nguồn.

**Hội đồng giải độc lập khác họ.** Một tác nhân giải lại cùng họ với model đã
viết câu hỏi vẫn có thể sai *cùng kiểu*: ở phản ví dụ tiếp tuyến–mặt cầu, nó
giải ra đúng giá trị sai mà đáp án ghi. Vì vậy bước này có thể chạy nhiều model
thuộc các họ khác nhau (mỗi model trên một máy chủ riêng, cùng chỉ đọc đề bài),
và gộp kết quả theo hai luật cố ý không đối xứng:

- *xác nhận* đòi **mọi** thành viên (hoặc ít nhất k thành viên, tuỳ cấu hình)
  cùng ra giá trị của đáp án, và không thành viên nào ra giá trị khác;
- *gắn cờ* chỉ cần **một** thành viên ra một giá trị dứt khoát khác đáp án — câu
  khi đó chuyển người duyệt, kể cả khi hội đồng không đạt đồng thuận.

Nhãn "đã kiểm chứng độc lập" là một lời hứa với người dùng, còn một cờ thừa chỉ
tốn một lượt duyệt tay. Mỗi lần chạy ghi lại họ của từng model và cảnh báo khi
mọi thành viên cùng họ với model sinh câu hỏi. Khi một thành viên **không chạy
được** (hết thời gian chờ, máy chủ lỗi), câu được đánh dấu *kiểm chứng chưa
trọn* và đếm riêng — không bị gộp vào nhóm "không kiểm được bằng máy"; còn lỗi
cấu hình (sai khoá truy cập, hết hạn mức) thì dừng cả lượt chạy.

**Verifier** — hoàn toàn tất định, không gọi LLM. Kỹ thuật:

- **Kiểm chứng bằng chương trình (program-aided verification, hướng
  PAL/Program-of-Thought)** [6], [7]: biểu thức kiểm chứng do Writer soạn được chạy
  thật bằng **SymPy** [11] (tính ký hiệu: đạo hàm, tích phân, giải phương trình…)
  kèm đối chiếu số học tại nhiều điểm — đáp án được *máy tính lại*, không phải
  LLM tự nhận đúng. Đây là chốt chặn đặc thù cho môn Toán mà các pipeline AQG
  thuần LLM không có.
- **Phân xử đa nguồn → 5 trạng thái**: thay vì một nhãn "đã kiểm chứng" duy
  nhất, hệ thống đối chiếu đáp án đã chọn với biểu thức của Writer và với mục
  tiêu độc lập, rồi kết luận một trong năm trạng thái:
  - *đã kiểm chứng độc lập* — nguồn tính toán độc lập cho cùng đáp án;
  - *nhất quán* — biểu thức của Writer khớp đáp án, chưa có gì mạnh hơn;
  - *lệch nguồn* — các nguồn tính toán không thống nhất;
  - *không kiểm được bằng máy* — câu khái niệm/chứng minh, không có phép tính
    nào để chạy;
  - *bị bác bỏ* — tính toán độc lập chỉ ra đáp án khác, hoặc có nhiều hơn một
    phương án đúng.
  Đây chính là nhãn hiển thị cho người dùng: một câu mới chỉ *nhất quán với
  chính nó* không bao giờ hiện cùng nhãn với câu đã có nguồn độc lập xác nhận,
  và câu khái niệm hiện thẳng "không kiểm được" chứ không để trống cho người
  dùng tự hiểu là đã kiểm.
- **Loại trừ đa đáp án (multi-answer elimination)**: chạy cùng bộ kiểm chứng
  trên cả 3 phương án nhiễu; phương án nào cũng được xác nhận đúng → cả câu bị
  loại (đề có hơn một đáp án đúng).
- **Tự sửa đáp án (answer-key repair) — chỉ khi có bằng chứng độc lập**: nếu
  đáp án ghi trong câu không khớp kết quả máy tính nhưng một phương án nhiễu lại
  khớp, hệ thống chỉ được hoán đổi hai bên khi **mục tiêu độc lập xác nhận giá
  trị mới**. Sửa dựa vào một mình biểu thức của Writer thì cũng dễ viết đè lên
  một đáp án đúng như dễ sửa được một đáp án sai; không đủ bằng chứng thì câu
  chuyển sang người duyệt, không tự sửa.
- **Chính sách "không khớp ≠ sai"**: khi các nguồn lệch nhau, không loại ngay —
  đa số ca lệch do biểu thức kiểm chứng viết không đúng đề chứ không phải model
  giải sai (thực đo chỉ ~1/12 ca sai thật). Câu được giữ nhưng **bắt buộc vào
  hàng chờ người duyệt tay**.
- **Soát lỗi soạn trắc nghiệm (Item-Writing Flaws — IWF, rule-based)** [12]: bộ
  quy tắc từ lĩnh vực đo lường giáo dục soát các lỗi ra đề kinh điển — phương
  án trùng/gần trùng nhau, độ dài lệch hẳn (đáp án dài nhất thường là đáp án
  đúng), từ tuyệt đối kiểu "luôn luôn/không bao giờ", thang số không cân đối,
  format không đồng nhất giữa các phương án.
- **Kiểm tra quy tắc chung**: schema, trích dẫn nguồn phải hợp lệ (có cơ chế
  tự sửa trích dẫn lệch bằng cách dò lại trong tài liệu), lời giải đủ chất lượng.

**Critic** — chấm chất lượng bằng LLM. Kỹ thuật:

- **LLM-as-a-judge với model bất đối xứng** [13]: model chấm (gpt-4o-mini) nhẹ và rẻ
  hơn model sinh (gpt-4o) — chấm là bài dễ hơn sinh, dùng model to cho việc này
  là lãng phí.
- **Nhận định trước, điểm sau (rationale-before-score, theo hướng RMTS —
  rationale-based multi-trait scoring)** [14]: với từng tiêu chí, model buộc phải
  viết nhận định *rồi mới* cho điểm — chống thói cho điểm bừa rồi bịa lý do,
  và nhận định lưu lại làm bằng chứng cho người duyệt.
- **Chấm đa tiêu chí theo rubric (multi-trait rubric scoring)**: 6 tiêu chí
  thang 0–1 — rõ ràng, chiều sâu tư duy, khớp mức Bloom, độ hợp lý phương án
  nhiễu, tính duy nhất đáp án (dưới 0.5 → loại, nghi đề nhiều đáp án đúng),
  nhất quán lỗi–giá trị — thay vì một điểm tổng mù mờ.
- **Chấm bám nguồn trên tài liệu gốc (grounding / faithfulness check)**: Critic
  nhận chính tài liệu PDF đính kèm và đối chiếu từng dữ kiện trong đề / đáp án
  / lời giải / trích dẫn — dữ kiện bịa không có trong tài liệu kéo điểm bám
  nguồn xuống, dưới 0.4 là loại.
- **Kiểm nhất quán lỗi–giá trị (theo lối đánh giá của LookAlike)** [10]: làm theo
  đúng chuỗi lỗi mà Distractor mô tả có ra đúng giá trị phương án nhiễu không;
  lời giải có nhất quán với đáp án không — bắt lớp lỗi "giải thích một đằng,
  con số một nẻo" (dưới 0.4 → loại).
- **An toàn khi chính giám khảo lỗi (fail-open)**: Critic gặp sự cố/parse hỏng
  thì không chặn câu — điền điểm trung tính và để Formatter + người duyệt quyết,
  tránh một lỗi hạ tầng chấm điểm giết oan cả lượt sinh.

Trong các ứng viên sống sót, chọn câu tốt nhất theo thứ tự ưu tiên: đã được
kiểm chứng toán học → điểm chất lượng → điểm bám nguồn.

**Formatter** — tất định, đóng gói bản ghi cuối. Kỹ thuật:

- **Trộn vị trí phương án (chống position bias)** [15]: đáp án đúng được xáo ngẫu
  nhiên vào A/B/C/D — LLM có thói đặt đáp án đúng ở vị trí quen thuộc, không
  trộn thì học sinh (và model chấm) đoán được mẫu.
- **Ước lượng độ khó** cho từng câu từ các tín hiệu đã thu (mức Bloom, điểm
  chấm, độ phức tạp lời giải).
- **Phân luồng cho người duyệt (human-in-the-loop triage)**: mọi tín hiệu nghi
  ngờ tích luỹ dọc pipeline được quy về một trong hai trạng thái — *chờ duyệt*
  hay *cần sửa* — kèm danh sách lý do, để người duyệt biết soi câu nào trước:

- Tính duy nhất đáp án thấp, lệch mức Bloom, hoặc kiểm chứng gặp lỗi → ép điểm
  chất lượng xuống ≤0.5 và chuyển **cần sửa** (needs_revision) kèm lý do.
- Điểm chất lượng/bám nguồn sát ngưỡng → **cần sửa**.
- Kiểm chứng toán không khớp → luôn **cần sửa** (nhưng không trừ điểm — câu
  đúng mà biểu thức kiểm chứng lệch vẫn được xếp hạng công bằng).
- Còn lại → **chờ duyệt** (pending_review).

Cuối cùng câu được so trùng đề với các câu đã nhận trong cùng lượt; trùng thì
loại, không thì **được chấp nhận** và mang theo nhãn chuẩn đầu ra đã gán.

### Câu bị loại không bị vứt đi

Mọi điểm loại (Writer không sinh được, thiếu phương án nhiễu, Verifier bác,
Critic chấm rớt, đóng gói lỗi, trùng lặp, lỗi hệ thống) đều được ghi lại thành
bản ghi có **mã lý do** và giữ tối đa 80 bản ghi mỗi lượt — hiển thị ở tab
**"Từ chối"** trên giao diện để người dùng thấy vì sao và ở khâu nào câu bị loại.

## ③ Hậu xử lý và lưu kết quả

1. **Kiểm chứng nhãn chuẩn đầu ra**: một lần gọi LLM (dạng text, không cần đọc
   PDF) nhận toàn bộ câu đã sinh + danh sách chuẩn đầu ra, gán lại nhãn cho
   từng câu — nhãn sơ bộ gán từ lúc sinh được kiểm chứng/bổ sung. Lỗi ở bước
   này chỉ làm mất nhãn, không hỏng kết quả.
2. **Lưu kết quả**: bộ câu hỏi kèm siêu dữ liệu — model dùng, số câu yêu
   cầu/đạt, số lỗi từng loại, thống kê theo chủ đề / mức Bloom / chuẩn đầu ra /
   trạng thái duyệt, **chi phí token** và thời gian chạy. Danh sách câu bị loại
   lưu riêng kèm tổng hợp lý do.

## ④ Người dùng duyệt — vòng lặp con người

Tất cả thao tác dưới đây diễn ra trên cùng một job, không phải upload lại:

- **Duyệt từng câu**: chấp nhận, hoặc đánh dấu cần sửa.
- **👎 Sinh lại câu bị chê**: các câu bị đánh giá kém bị thay, câu còn lại giữ
  nguyên. Toàn bộ phản hồi được tổng hợp thành **hồ sơ sở thích** tiêm vào
  prompt của Writer/Distractor — và được lưu lại vĩnh viễn cho job, nên mọi
  lượt sinh sau (kể cả sinh thêm) vẫn tôn trọng ý người dùng. Đề của tất cả câu
  cũ được đưa vào danh sách cấm lặp.
- **Sinh thêm**: thêm 1–20 câu mới từ cùng tài liệu, giữ nguyên câu cũ, cùng cơ
  chế hồ sơ sở thích + cấm lặp.
- **Luyện tập**: làm thử bộ câu ngay trên hệ thống, có chấm và giải thích.
- **Export** bộ câu ra file.

## ⑤ Ngân hàng câu hỏi

Câu đạt yêu cầu được thêm vào ngân hàng dùng chung. Trước khi thêm, từng câu
được kiểm tra trùng lặp **3 tầng**, từ rẻ đến đắt:

1. **Trùng nguyên văn** đề bài.
2. **Gần trùng** — đề bài sau chuẩn hoá giống nhau ≥ 85%.
3. **Trùng ngữ nghĩa** — embedding phần tóm tắt câu hỏi (Gemini
   `gemini-embedding-001`, 3072 chiều) [16], cosine ≥ 0.82 tính là trùng. Câu cũ
   trong bank chưa có embedding được bổ sung tự động khi so. Không có embedding
   thì rơi về so trùng bằng LLM từng cặp (chậm hơn nhiều — trước khi dùng
   Gemini, bước này mất ~42s; giờ ~4s).

Câu bị phát hiện trùng xử lý theo lựa chọn của người dùng: **bỏ qua** (mặc
định), **thay thế** câu cũ, hoặc **vẫn thêm**.

---

## Tổng kết chi phí cho một câu hỏi thành công

Đường đi suôn sẻ (không thử lại) tốn **3 lần gọi LLM** — Writer, Distractor,
Critic — cộng 2 lần gọi dùng chung cho cả lượt (trích dàn ý lúc chuẩn bị, kiểm
chứng nhãn chuẩn đầu ra lúc kết thúc). Verifier và Formatter chạy thuần CPU,
không tốn lần gọi nào.

---

## Tài liệu tham khảo

- [1] M. Heilman, N. A. Smith. *Good Question! Statistical Ranking for Question
  Generation*. NAACL-HLT, 2010.
- [2] A. Dutulescu. *Generating Multiple-Choice Questions with Large Language
  Models*. University Politehnica of Bucharest (advisors: S. Ruseti,
  M. Dascalu), 2024.
- [3] L. Ouyang et al. *Training Language Models to Follow Instructions with
  Human Feedback*. NeurIPS, 2022.
- [4] H. Luo, Y. Deng, Y. Shen, S.-K. Ng, T.-S. Chua. *Chain-of-Exemplar:
  Enhancing Distractor Generation for Multimodal Educational Question
  Generation*. ACL, 2024.
- [5] J. Wei et al. *Chain-of-Thought Prompting Elicits Reasoning in Large
  Language Models*. NeurIPS, 2022.
- [6] L. Gao et al. *PAL: Program-aided Language Models*. ICML, 2023.
- [7] W. Chen, X. Ma, X. Wang, W. W. Cohen. *Program of Thoughts Prompting:
  Disentangling Computation from Reasoning for Numerical Reasoning Tasks*.
  TMLR, 2023.
- [8] L. W. Anderson, D. R. Krathwohl. *A Taxonomy for Learning, Teaching, and
  Assessing: A Revision of Bloom's Taxonomy of Educational Objectives*.
  Longman, 2001.
- [9] N. Fernandez, A. Scarlatos, S. Woodhead, A. Lan. *DiVERT: Distractor
  Generation with Variational Errors Represented as Text for Math
  Multiple-choice Questions*. EMNLP, 2024.
- [10] N. Parikh, N. Fernandez, A. Scarlatos, S. Woodhead, A. Lan. *LookAlike:
  Consistent Distractor Generation in Math MCQs*. BEA Workshop (ACL),
  arXiv:2505.01903, 2025.
- [11] A. Meurer et al. *SymPy: Symbolic Computing in Python*. PeerJ Computer
  Science 3:e103, 2017.
- [12] T. M. Haladyna, S. M. Downing, M. C. Rodriguez. *A Review of
  Multiple-Choice Item-Writing Guidelines for Classroom Assessment*. Applied
  Measurement in Education 15(3), 2002.
- [13] L. Zheng et al. *Judging LLM-as-a-Judge with MT-Bench and Chatbot
  Arena*. NeurIPS Datasets and Benchmarks, 2023.
- [14] S. Chu, J. W. Kim, B. Wong, M. Y. Yi. *Rationale Behind Essay Scores:
  Enhancing S-LLM's Multi-Trait Essay Scoring with Rationale Generated by LLMs*
  (RMTS). Findings of NAACL 2025, arXiv:2410.14202.
- [15] C. Zheng, H. Zhou, F. Meng, J. Zhou, M. Huang. *Large Language Models
  Are Not Robust Multiple Choice Selectors*. ICLR, 2024.
- [16] J. Lee et al. *Gemini Embedding: Generalizable Embeddings from Gemini*.
  arXiv:2503.07891, 2025.
