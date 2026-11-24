# Kiểm toán Agent Harness · AgentSociety (v2.12.0 Active Scope)

Skill 2.0.0 · Phương pháp 2.0.0 · Schema 2.0.0 · Giao diện 2.0.0

## Kết luận

**Có Agent Harness** · Mức 3/4 · Ứng dụng tự xây dựng (lai SDK/Framework: tự sở hữu vòng đời trên LiteLLM, Ray, MCP SDK, FAISS) · Tin cậy high.

AgentSociety v2 triển khai đầy đủ kiến trúc Agent Harness phân lớp do ứng dụng tự sở hữu vòng đời: (1) AgentBase/PersonAgent sở hữu vòng lặp ReAct đa bước, prompt-prefix caching, memory consolidation, TODO và AgentSkillRuntime với worker subprocess cô lập; (2) CodeGenRouter/ReActRouter/PlanExecuteRouter sở hữu lớp trung gian LLM-tool với AST safety guard và Linux process sandbox; (3) AgentSociety sở hữu vòng đời mô phỏng phân tán trên Ray Tasks với checkpoint/resume 2 tệp nguyên tử; (4) Analysis Harness cung cấp deterministic CLI harness có phase gates cho AI agent ngoài. Xếp Mức 3 (không phải Mức 4) vì chưa có bằng chứng vận hành đầu-cuối (runtime\_coverage\_pct=0%) và còn lỗ hổng bảo mật in-process ở Backend custom module cùng lỗi logic replan ở AgentSocietyHelper. [EV-005](#EV-005) [EV-007](#EV-007) [EV-009](#EV-009) [EV-015](#EV-015) [EV-020](#EV-020) [EV-023](#EV-023)

- **Trưởng thành kiến trúc** · 66,67/100 · 12/12 nhóm đủ căn cứ.
- **Phù hợp với yêu cầu** · 66,67% · 12/12 nhóm có kết quả đối chiếu yêu cầu.
- **Độ phủ bằng chứng** · 100%
- **Kiểm chứng đầu-cuối** · 0/4 luồng. partial\_fixture\_only

## Phạm vi và điều kiện tái lập

- **Thời điểm** · 2026-11-24
- **Nhánh** · main
- **Commit** · e7186aad430e4c392b6d1c252120bffea8d9c900
- **Snapshot** · d:/PROJECTS/AgentSociety @ main (e7186aad430e, working tree clean)

### Phạm vi khảo sát

- packages/agentsociety2/ (Python SDK v2.12.0 — trọng tâm kiểm toán)
- extension/ (VS Code extension ai-social-scientist v1.10.0 — phân tách vai trò workbench)
- frontend/ (React + Vite web console — ranh giới giao diện)
- Ngoài phạm vi active: packages/agentsociety/ (v1 legacy), agentsociety-community, agentsociety-benchmark, và các dịch vụ bên ngoài (LLM API, MCP gateway https://llmapi.fiblab.net/mcp/, Claude Code/Codex CLI).

### Công cụ kiểm toán

- Đọc trực tiếp mã nguồn &amp; truy vết luồng thực thi (file:line, symbol)
- Kiểm tra fixture cô lập trên Python 3.13.15 (WorkspaceFS, AgentMemoryStore, path\_security)
- Đối chiếu manifest (pyproject.toml, uv.lock, extension/package.json)

### Giới hạn

- Môi trường kiểm toán cục bộ chạy Windows với Python 3.13.15, chưa cài uv/.venv và thiếu các gói litellm, ray, faiss-cpu, mcp, duckdb, pytest; do đó chưa chạy được bộ 46 pytest hay mô phỏng đầu-cuối (E2E) với LLM/Ray thật.
- Process sandbox của CodeGenRouter (codegen\_worker.py) chỉ hoạt động trên Linux nên không thể kiểm thử thực nghiệm RLIMIT/prctl trên máy Windows.
- Chưa kiểm tra dịch vụ ngoài (LLM gateway, MCP server https://llmapi.fiblab.net/mcp/, và plugin ngoài paper-toolkit).

## Kiểm kê và bản đồ kiến trúc


### Đơn vị triển khai

- **packages/agentsociety2** · SDK lõi chứa toàn bộ Agent Harness, Env Routers, Society Orchestrator, Analysis Harness và FastAPI Backend (v2.12.0) [EV-001](#EV-001) [EV-003](#EV-003) [EV-005](#EV-005) [EV-020](#EV-020) (active\_audited).
- **extension** · VS Code Workbench (ai-social-scientist v1.10.0) quản lý Backend, mở Claude Code/Codex và đồng bộ cấu hình MCP [EV-001](#EV-001) [EV-030](#EV-030) (active\_audited\_boundary).
- **frontend** · Web dashboard React + Vite giao tiếp Backend API [EV-001](#EV-001) (active\_boundary\_only).

### Vai trò tác tử

- **PersonAgent (trên AgentBase)** · Tác tử mô phỏng con người chạy vòng lặp ReAct đa bước, gắn workspace, có memory, TODO và skill runtime [EV-005](#EV-005) [EV-007](#EV-007) [EV-011](#EV-011) (implemented\_static).
- **AgentSocietyHelper** · Tác tử phụ trợ Plan-and-Execute XML phục vụ truy vấn/can thiệp xã hội (ask/intervene) với 6 tool [EV-022](#EV-022) (implemented\_with\_defect\_risk).
- **Contrib Specialized Agents (7 lớp)** · Các tác tử trò chơi/thực nghiệm kế thừa AgentBase (public\_goods, prisoners\_dilemma, trust\_game, llm\_donor\_agent, ...) [EV-012](#EV-012) (implemented\_static).

### Trách nhiệm của các thành phần

- **AgentBase &amp; AgentSkillRuntime** · Harness lõi của tác tử: quản lý vòng lặp ReAct, tool dispatch, bảo vệ workspace, skill metadata-first và skill\_worker.py [EV-005](#EV-005) [EV-006](#EV-006) [EV-009](#EV-009) [EV-010](#EV-010) [EV-031](#EV-031) (implemented\_static).
- **Env Routers &amp; CodeGen Sandbox** · Harness trung gian gồm đủ 6 router (CodeGenRouter, ReActRouter, PlanExecuteRouter, TwoTierReActRouter, TwoTierPlanExecuteRouter, SearchToolRouter) + AST guard + Linux process worker + FAISS template cache [EV-014](#EV-014) [EV-015](#EV-015) [EV-016](#EV-016) [EV-017](#EV-017) [EV-018](#EV-018) [EV-019](#EV-019) [EV-035](#EV-035) [EV-038](#EV-038) (implemented\_static).
- **AgentSociety Orchestrator &amp; Ray Runner** · Runtime điều phối N tác tử dạng Ray Tasks, QuestionnaireRunner khảo sát song song, quản lý đồng hồ mô phỏng và checkpoint/resume SOCIETY.json + SOCIETY\_STEP.json [EV-013](#EV-013) [EV-020](#EV-020) [EV-021](#EV-021) [EV-037](#EV-037) (implemented\_static).
- **Analysis Harness (CLI)** · Deterministic phase-gated CLI harness (0 lời gọi LLM) kiểm soát AI agent phân tích bên ngoài + experience memory [EV-023](#EV-023) (implemented\_static).
- **LLMClient &amp; AdaptiveSemaphore** · Bộ điều phối LLM per-event-loop trên LiteLLM, kiểm soát đồng thời AIMD, retry/timeout và chuẩn hóa thinking [EV-024](#EV-024) (implemented\_static).
- **ReplaySink &amp; ShardedAppendSink** · Lớp lưu trữ replay và trace OTel dạng 256 shard JSONL [EV-025](#EV-025) [EV-026](#EV-026) (implemented\_static).
- **FastAPI Backend** · Dịch vụ REST API đọc kết quả thí nghiệm, quản lý custom modules và skill marketplace [EV-028](#EV-028) [EV-029](#EV-029) [EV-033](#EV-033) [EV-036](#EV-036) (implemented\_with\_security\_gaps).
- **Research Skills (Experiment, Hypothesis, Literature)** · Bộ công cụ điều phối quy trình nghiên cứu (khởi tạo/theo dõi PID thí nghiệm, quản lý giả thuyết, truy vấn MCP tài liệu) [EV-027](#EV-027) [EV-037](#EV-037) (implemented\_static).

### Quan hệ và ranh giới

- **Society CLI (agentsociety)** · entrypoint. [EV-021](#EV-021)
- **VS Code Extension Workbench** · ui\_workbench. [EV-030](#EV-030)
- **FastAPI Backend (:8001)** · api\_service. [EV-028](#EV-028) [EV-029](#EV-029)
- **AgentSociety Orchestrator** · orchestrator. [EV-020](#EV-020)
- **AgentSocietyHelper (XML)** · agent\_helper. [EV-022](#EV-022)
- **Ray Batch Runner (step/questionnaire)** · runtime. [EV-013](#EV-013)
- **PersonAgent / AgentBase Harness** · agent\_harness. [EV-005](#EV-005) [EV-007](#EV-007)
- **AgentSkillRuntime &amp; skill\_worker** · tool\_sandbox. [EV-009](#EV-009) [EV-010](#EV-010)
- **EnvRouterActor (6 Routers: CodeGen/ReAct/Plan/TwoTier/Search)** · env\_harness. [EV-014](#EV-014) [EV-015](#EV-015) [EV-019](#EV-019) [EV-035](#EV-035)
- **CodeGen Worker (Linux Process / InProcess)** · sandbox. [EV-016](#EV-016)
- **Analysis Harness CLI (Phase Gates)** · deterministic\_harness. [EV-023](#EV-023)
- **LLMClient / LiteLLM + AIMD** · model\_gateway. [EV-024](#EV-024)
- **Workspace / ReplaySink / ShardedTrace** · storage. [EV-011](#EV-011) [EV-025](#EV-025) [EV-026](#EV-026) [EV-031](#EV-031)
- **External LLM Providers** · external\_service. [EV-024](#EV-024)
- **Literature MCP Gateway** · external\_service. [EV-027](#EV-027)
- Society CLI (agentsociety) → AgentSociety Orchestrator · khởi chạy &amp; --resume [EV-021](#EV-021) · Đối chiếu mã nguồn.
- VS Code Extension Workbench → FastAPI Backend (:8001) · HTTP REST &amp; quản lý tiến trình [EV-030](#EV-030) · Đối chiếu mã nguồn.
- VS Code Extension Workbench → Analysis Harness CLI (Phase Gates) · điều phối qua AI agent ngoài [EV-023](#EV-023) [EV-030](#EV-030) · Đối chiếu mã nguồn.
- AgentSociety Orchestrator → Ray Batch Runner (step/questionnaire) · fan-out batch (max\_retries=0) [EV-013](#EV-013) [EV-020](#EV-020) · Đối chiếu mã nguồn.
- AgentSociety Orchestrator → AgentSocietyHelper (XML) · ask() / intervene() [EV-020](#EV-020) [EV-022](#EV-022) · Đối chiếu mã nguồn.
- AgentSociety Orchestrator → EnvRouterActor (6 Routers: CodeGen/ReAct/Plan/TwoTier/Search) · init / step / checkpoint [EV-019](#EV-019) [EV-020](#EV-020) · Đối chiếu mã nguồn.
- Ray Batch Runner (step/questionnaire) → PersonAgent / AgentBase Harness · from\_workspace -&gt; step -&gt; to\_workspace [EV-013](#EV-013) · Đối chiếu mã nguồn.
- PersonAgent / AgentBase Harness → AgentSkillRuntime &amp; skill\_worker · hooks &amp; execute\_skill\_script [EV-006](#EV-006) [EV-009](#EV-009) · Đối chiếu mã nguồn.
- PersonAgent / AgentBase Harness → EnvRouterActor (6 Routers: CodeGen/ReAct/Plan/TwoTier/Search) · ask\_env() qua EnvRouterProxy [EV-006](#EV-006) [EV-019](#EV-019) · Đối chiếu mã nguồn.
- PersonAgent / AgentBase Harness → LLMClient / LiteLLM + AIMD · ReAct completion &amp; memory consolidation [EV-005](#EV-005) [EV-011](#EV-011) [EV-024](#EV-024) · Đối chiếu mã nguồn.
- PersonAgent / AgentBase Harness → Workspace / ReplaySink / ShardedTrace · AGENT.json, MEMORY.md, trace JSONL [EV-007](#EV-007) [EV-011](#EV-011) [EV-025](#EV-025) [EV-031](#EV-031) · Đối chiếu mã nguồn.
- EnvRouterActor (6 Routers: CodeGen/ReAct/Plan/TwoTier/Search) → CodeGen Worker (Linux Process / InProcess) · thực thi code sinh (AST guarded) [EV-015](#EV-015) [EV-016](#EV-016) · Đối chiếu mã nguồn.
- EnvRouterActor (6 Routers: CodeGen/ReAct/Plan/TwoTier/Search) → LLMClient / LiteLLM + AIMD · codegen / summary / embedding [EV-014](#EV-014) [EV-015](#EV-015) [EV-024](#EV-024) · Đối chiếu mã nguồn.
- AgentSocietyHelper (XML) → LLMClient / LiteLLM + AIMD · XML plan / replan / final answer [EV-022](#EV-022) [EV-024](#EV-024) · Đối chiếu mã nguồn.
- LLMClient / LiteLLM + AIMD → External LLM Providers · OpenAI / Anthropic API [EV-024](#EV-024) · Đối chiếu mã nguồn.
- FastAPI Backend (:8001) → Workspace / ReplaySink / ShardedTrace · đọc replay/log/artifacts &amp; ghi custom/skills [EV-028](#EV-028) [EV-029](#EV-029) [EV-033](#EV-033) · Đối chiếu mã nguồn.
- VS Code Extension Workbench → Literature MCP Gateway · cấu hình &amp; truy vấn literature MCP [EV-027](#EV-027) [EV-030](#EV-030) · Đối chiếu mã nguồn.

## Vòng đời tác tử

<a id="flow-FLOW-01"></a>

### FLOW-01 · PersonAgent Step &amp; ReAct Tool Loop

- **Điểm vào** · PersonAgent.step(tick, t) trong packages/agentsociety2/agentsociety2/agent/person.py:L538
- **Kết quả** · Chuỗi tóm tắt bước (hoặc \[idle-skip\]), cập nhật MEMORY.md/episodes.jsonl, TODO.json và trace spans
- **Phạm vi kiểm chứng** · Chưa xác minh E2E; đã kiểm fixture cô lập cho WorkspaceFS (EV-031) và AgentMemoryStore (EV-032) [EV-005](#EV-005) [EV-006](#EV-006) [EV-007](#EV-007) [EV-008](#EV-008) [EV-009](#EV-009) [EV-011](#EV-011)

1. **Khởi tạo &amp; pre\_step hooks** · Chạy \_ensure\_initialized(), làm mới visible skills và thực thi pre\_step lifecycle hooks; nếu idle\_skip\_enabled=True và đang ở đoạn sleep thì đi nhanh xác định (fail-open). [EV-007](#EV-007)
2. **Quan sát môi trường** · Gọi ask\_env('&lt;observe&gt;', readonly=True) kèm trace\_id/parent\_span\_id để thu nhận observation ban đầu. [EV-007](#EV-007) [EV-019](#EV-019)
3. **Xây dựng thread tối ưu prefix-cache** · build\_react\_messages() tạo 1 thread duy nhất mỗi step (base\_rules bất biến + &lt;agent&gt; + &lt;turn\_state&gt; + &lt;memory\_context&gt; + &lt;todo\_context&gt;), không cắt đầu. [EV-005](#EV-005) [EV-008](#EV-008)
4. **Vòng lặp ReAct &amp; gọi tool** · Lặp tối đa \_max\_react\_turns: gọi LLM, parse native tool calls hoặc text fallback, chạy song song đúng 5 action trong \_REACT\_PARALLEL\_SAFE\_ACTIONS (read/list/grep/read\_skill\_file/todo\_list) và tuần tự các tool còn lại (kể cả ask\_env/memory\_\*), bảo vệ tệp lõi (trả ok=True no-op), chuyển hướng env:\* sang ask\_env, làm mới &lt;todo\_context&gt;/&lt;active\_skills&gt; giữa step. [EV-005](#EV-005) [EV-006](#EV-006) [EV-009](#EV-009)
5. **Kết thúc &amp; hợp nhất bộ nhớ** · Thu finish(memories=...), chạy post\_step hooks và gọi memory\_runtime.after\_step() ghi episodes.jsonl + hợp nhất MEMORY.md khi đạt ngưỡng. [EV-005](#EV-005) [EV-007](#EV-007) [EV-011](#EV-011)
- **Nhánh thành công** · Model gọi tool finish hợp lệ -&gt; trả về tóm tắt và lưu inline memories không cần lượt LLM tách rời. [EV-005](#EV-005)
- **Nhánh lỗi** · Model xuất tool call sai schema/không hợp lệ -&gt; retry 1 lần trong lượt với &lt;schema\_error&gt; phản hồi từng tool\_call\_id; nếu tool lỗi thì trả 'ERROR: ...' vào thread. [EV-005](#EV-005) [EV-006](#EV-006)
- **Nhánh phục hồi** · Cạn \_max\_react\_turns mà chưa gọi finish -&gt; tổng hợp \_synthesize\_step\_fallback\_memory() (step mode) hoặc \_synthesize\_ask\_fallback() (ask mode) để bảo toàn tiến độ. [EV-005](#EV-005)
<a id="flow-FLOW-02"></a>

### FLOW-02 · CodeGenRouter &amp; Isolated Sandbox Execution

- **Điểm vào** · EnvRouterProxy.ask() -&gt; CodeGenRouter.ask() tại packages/agentsociety2/agentsociety2/env/router\_codegen.py:L2404
- **Kết quả** · Tuple (ctx, answer) kèm trạng thái thực thi và cập nhật FAISS template cache nếu hợp lệ
- **Phạm vi kiểm chứng** · Chưa xác minh E2E (thiếu LLM/FAISS/Linux sandbox trên máy kiểm toán Windows) [EV-014](#EV-014) [EV-015](#EV-015) [EV-016](#EV-016) [EV-019](#EV-019)

1. **Định tuyến qua EnvRouterProxy** · Gửi RPC tới EnvRouterActor với timeout 900s (max\_concurrency=64 nếu mọi module concurrency-safe, ngược lại 1). [EV-019](#EV-019)
2. **Chuỗi cung cấp mã (Provider Chain)** · Thử lần lượt PredefinedCodeProvider -&gt; NormalizedInstructionProvider (mặc định tắt) -&gt; CacheCodeProvider (exact match rồi FAISS IndexFlatIP trên HMAC-signed cache.pkl) -&gt; LLMCodegenProvider. [EV-015](#EV-015)
3. **Kiểm tra an toàn AST &amp; chèn deadline** · CodeStage.\_validate\_code\_safety chặn dunder/eval/exec/module nguy hiểm, chèn \_ExecutionGuards deadline vào vòng lặp/hàm và kiểm tra gán results\['status'\]. [EV-015](#EV-015)
4. **Thực thi trong Sandbox &amp; tổng hợp** · Chạy trên Linux process worker (python -I -S, RLIMIT\_AS=512MiB, NOFILE=64, wall-clock 10s, RPC tool về parent kiểm readonly) hoặc inprocess trên non-Linux; SummaryStage xuất kết quả xác định từ stdout. [EV-015](#EV-015) [EV-016](#EV-016)
- **Nhánh thành công** · Code chạy sạch, trả results\['status'\] hợp lệ -&gt; lưu mẫu vào TemplateCacheDB (HMAC-SHA256) và trả về cho tác tử. [EV-015](#EV-015)
- **Nhánh lỗi** · Code vi phạm AST hoặc lỗi runtime -&gt; lặp sửa mã tối đa max\_llm\_call\_retry=10; dừng ngay không retry nếu finish\_reason=='length' hoặc write\_attempted==True để tránh lặp side-effect ghi. [EV-015](#EV-015)
- **Nhánh phục hồi** · Worker timeout/crash trên Linux -&gt; WorkerPool.lease() gọi os.killpg(..., SIGKILL) và hủy worker hỏng, không tái sử dụng; EnvRouterProxy gọi ray.cancel khi quá hạn RPC. [EV-016](#EV-016) [EV-019](#EV-019)
<a id="flow-FLOW-03"></a>

### FLOW-03 · AgentSociety CLI Simulation &amp; Crash-Safe Resume

- **Điểm vào** · agentsociety CLI (packages/agentsociety2/agentsociety2/society/cli.py:L971) -&gt; AgentSociety.init()/step()
- **Kết quả** · Hoàn tất kịch bản steps.yaml, ghi sharded replay JSONL, artifacts và cập nhật SOCIETY\_STEP.json
- **Phạm vi kiểm chứng** · Chưa xác minh E2E (thiếu Ray/.venv/LLM key) [EV-013](#EV-013) [EV-014](#EV-014) [EV-020](#EV-020) [EV-021](#EV-021)

1. **Pre-flight &amp; tạo workspace** · Kiểm tra biến môi trường, chặn ghi đè run\_dir cũ, fan-out create\_agents\_batch tạo thư mục agent\_XXXX, ghi SOCIETY.json (schema\_version=2) một lần duy nhất. [EV-020](#EV-020) [EV-021](#EV-021)
2. **Đánh dấu tick &amp; fan-out Ray Tasks** · Ghi pending\_update='tick' vào SOCIETY\_STEP.json, fan-out step\_agent\_batch.options(max\_retries=0) theo batch\_size=256 (mỗi worker from\_workspace -&gt; step -&gt; to\_workspace -&gt; close). [EV-013](#EV-013) [EV-020](#EV-020)
3. **Tiến môi trường &amp; commit nguyên tử** · Chạy env\_router.step(tick, t) (timeout 900s), gọi env\_router.to\_workspaces(), ghi SOCIETY\_STEP.json mới với pending\_update=None và tăng step\_count. [EV-014](#EV-014) [EV-020](#EV-020)
4. **Phục hồi qua --resume** · \_read\_checkpoint() kiểm tra schema\_version==2 và pending\_update is None, khôi phục seed/env state/agent workspace và bỏ qua bước &lt; completed\_step\_count. [EV-020](#EV-020) [EV-021](#EV-021)
- **Nhánh thành công** · Tất cả batch và env module hoàn tất -&gt; commit SOCIETY\_STEP.json nguyên tử và tiến sang bước tiếp theo. [EV-020](#EV-020)
- **Nhánh lỗi** · Có lỗi agent/batch -&gt; lưu best-effort trạng thái agent, ghi bảng core\_step\_failures, raise RuntimeError và giữ nguyên pending\_update='tick' (không gọi env.step). [EV-013](#EV-013) [EV-020](#EV-020)
- **Nhánh phục hồi** · Nếu crash giữa tick/intervention, lần --resume sau sẽ từ chối chạy (fail-closed ValueError) do pending\_update!=None để tránh dữ liệu lệch trạng thái. [EV-020](#EV-020)
<a id="flow-FLOW-04"></a>

### FLOW-04 · Analysis Harness Phase-Gated Workflow &amp; Experience Memory

- **Điểm vào** · python -m agentsociety2.skills.analysis.harness.cli (packages/agentsociety2/agentsociety2/skills/analysis/harness/)
- **Kết quả** · Báo cáo phân tích song ngữ đã qua review độc lập, artifact manifest và bài học/công thức trong experience memory
- **Phạm vi kiểm chứng** · Chưa xác minh runtime (analysis/\_\_init\_\_.py kéo duckdb chưa cài trong Python local) [EV-023](#EV-023)

1. **Khởi tạo &amp; Preflight** · evaluate\_operation\_availability kiểm tra input, capabilities, depends\_on\_gates; execute\_operation khóa file theo execution\_key và ghi OperationRunReceipt. [EV-023](#EV-023)
2. **Cổng pha 2 lớp (Dual-layer Gate)** · Mỗi pha (frame-&gt;explore-&gt;claims-&gt;refine-&gt;produce-&gt;synthesis) phải vượt qua validator cấu trúc xác định và PhaseAttestation từ AI agent bên ngoài. [EV-023](#EV-023)
3. **Kiểm chứng phát hành (Release Gate)** · validate-release kiểm tra đồng thời đủ tệp song ngữ, chất lượng báo cáo và kết quả report-reviewer độc lập (verdict==PASS, score&gt;=4, khớp SHA-256 report\_fingerprint). [EV-023](#EV-023)
4. **Experience Memory 4 bước** · draft-reflection -&gt; record-feedback -&gt; review-reflection (chặn thiếu bằng chứng hoặc chưa xác nhận preference) -&gt; promote-reflection (chống trùng) và tự nạp lại vào phiên sau. [EV-023](#EV-023)
- **Nhánh thành công** · Đạt cả structural validator và attestation -&gt; cho phép cmd\_advance sang pha kế tiếp (exit code 0). [EV-023](#EV-023)
- **Nhánh lỗi** · Thiếu rubric, nhảy cóc pha hoặc artifact bị sửa sau khi attest (attestation\_stale qua SHA-256) -&gt; trả BLOCKED (exit code 2). [EV-023](#EV-023)
- **Nhánh phục hồi** · Tác tử bên ngoài chạy lại bước bị chặn theo fix hint và gọi record-attestation mới để cập nhật fingerprint. [EV-023](#EV-023)

## Ma trận năng lực C1–C12


### C1 · Vòng lặp thực thi

- **Mức trưởng thành** · 3/4 · Áp dụng · Đã triển khai.
- **Xác minh** · Mã nguồn Đã xác minh. Thực thi Chưa xác minh. Tin cậy Cao.
- **Thực thi đã khảo sát** · Chưa xác minh runtime (thiếu .venv/LLM key)
- **Cơ chế** · AgentBase.run\_react\_loop và CodeGenRouter triển khai vòng lặp đa bước chặt chẽ (phản hồi tool, retry schema/code, dừng ngay khi write\_attempted, fallback). Điểm trừ: 2/6 env routers (ReActRouter và TwoTierReActRouter) đều đặt tools=None từ bước &gt;=2 và run\_react\_loop thiếu wall-clock timeout tổng. [EV-005](#EV-005) [EV-007](#EV-007) [EV-014](#EV-014) [EV-015](#EV-015) [EV-017](#EV-017) [EV-035](#EV-035)
- **Giới hạn** · ReActRouter và TwoTierReActRouter bỏ tools ở bước &gt;=2; thiếu wall-clock timeout cấp vòng lặp ReAct.
- **Đáp ứng yêu cầu** · Một phần. Hỗ trợ vòng lặp tác tử LLM-native đa bước và nhiều mẫu suy luận (CodeGen, ReAct, Plan-Execute) theo README/CLAUDE.md. [EV-002](#EV-002) [EV-005](#EV-005) [EV-015](#EV-015)

### C2 · Kỹ thuật context

- **Mức trưởng thành** · 3/4 · Áp dụng · Đã triển khai.
- **Xác minh** · Mã nguồn Đã xác minh. Thực thi Chưa xác minh. Tin cậy Cao.
- **Thực thi đã khảo sát** · Chưa xác minh runtime
- **Cơ chế** · Thread append-only, base\_rules bất biến, json\_block sort\_keys=True, làm mới chọn lọc &lt;todo\_context&gt;/&lt;active\_skills&gt;, giới hạn đọc tệp 64 KiB và memory\_context\_max\_chars. Điểm trừ: khai báo tiktoken nhưng chưa dùng để ép token budget chủ động trước khi gọi LLM. [EV-003](#EV-003) [EV-005](#EV-005) [EV-007](#EV-007) [EV-008](#EV-008) [EV-024](#EV-024)
- **Giới hạn** · Chưa có bộ đo và nén theo token budget chủ động (chỉ fail-fast khi provider báo vượt cửa sổ).
- **Đáp ứng yêu cầu** · Đáp ứng. Quản lý ngữ cảnh ổn định, hỗ trợ prompt-prefix caching và tải skill theo metadata cho mô phỏng nhiều bước. [EV-002](#EV-002) [EV-005](#EV-005) [EV-008](#EV-008)

### C3 · Bộ nhớ và trạng thái

- **Mức trưởng thành** · 3/4 · Áp dụng · Đã triển khai.
- **Xác minh** · Mã nguồn Đã xác minh. Thực thi Test có fixture. Tin cậy Cao.
- **Thực thi đã khảo sát** · Đã kiểm fixture cô lập cho AgentMemoryStore
- **Cơ chế** · Tách rõ trạng thái bất biến (config.json, SOCIETY.json) và trạng thái tiến độ (AGENT.json, MEMORY.md, episodes.jsonl, TODO.json, SOCIETY\_STEP.json) ghi nguyên tử; Analysis Harness có experience memory 4 bước. Điểm trừ: mem0ai khai báo dependency lõi nhưng không dùng ở PersonAgent; AskStep/QuestionnaireStep thiếu cờ pending\_update. [EV-003](#EV-003) [EV-011](#EV-011) [EV-012](#EV-012) [EV-020](#EV-020) [EV-023](#EV-023) [EV-026](#EV-026) [EV-032](#EV-032)
- **Giới hạn** · Dependency mem0ai dư thừa trên đường chính; AskStep/QuestionnaireStep chưa đánh dấu pending\_update khi crash.
- **Đáp ứng yêu cầu** · Đáp ứng. Tác tử dạng bản ghi không trạng thái gắn workspace, có bộ nhớ dài/ngắn hạn và hỗ trợ --resume an toàn sau sự cố. [EV-002](#EV-002) [EV-011](#EV-011) [EV-020](#EV-020)

### C4 · Tool và MCP

- **Mức trưởng thành** · 3/4 · Áp dụng · Một phần.
- **Xác minh** · Mã nguồn Đã xác minh. Thực thi Chưa xác minh. Tin cậy Cao.
- **Thực thi đã khảo sát** · Chưa xác minh runtime
- **Cơ chế** · AgentBase hỗ trợ native tool call + text fallback, AgentSkillRuntime chạy custom skill qua skill\_worker.py; EnvBase dùng mcp SDK làm JSON Schema builder nội bộ (EnvMeta.\_\_new\_\_ không kế thừa @tool của concrete subclass); giao thức MCP thực tế nằm ở skills/literature/mcp\_client.py và extension/src/services/mcpClient.ts. Điểm trừ kỹ thuật: mcp\_client.py mở 2 phiên HTTP/MCP liên tiếp mỗi lần gọi không retry, và 2 router ReAct đánh rơi tools từ bước &gt;=2. [EV-006](#EV-006) [EV-009](#EV-009) [EV-010](#EV-010) [EV-027](#EV-027) [EV-030](#EV-030) [EV-035](#EV-035) [EV-037](#EV-037)
- **Giới hạn** · MCP client mở 2 session không retry; ReActRouter/TwoTierReActRouter bỏ tools từ bước &gt;=2; EnvMeta không kế thừa @tool.
- **Đáp ứng yêu cầu** · Một phần. Hỗ trợ công cụ môi trường cắm nóng, skill mở rộng và tích hợp MCP theo README. [EV-002](#EV-002) [EV-009](#EV-009) [EV-027](#EV-027)

### C5 · Lập kế hoạch

- **Mức trưởng thành** · 2/4 · Áp dụng · Một phần.
- **Xác minh** · Mã nguồn Đã xác minh. Thực thi Chưa xác minh. Tin cậy Cao.
- **Thực thi đã khảo sát** · Chưa xác minh runtime
- **Cơ chế** · Có PlanExecuteRouter (plan + replan tối đa 3 lần), AgentSocietyHelper (XML plan + replan tối đa 2 lần), TodoStateStore trong PersonAgent và quy trình pha trong Analysis Harness. Điểm trừ: AgentSocietyHelper.\_run dùng step\_index=len(execution\_history) sau khi thay plan mới, dễ thoát sớm; chưa có DAG thực thi phụ thuộc song song. [EV-007](#EV-007) [EV-018](#EV-018) [EV-022](#EV-022) [EV-023](#EV-023) [EV-035](#EV-035)
- **Giới hạn** · Lỗi chỉ số step\_index sau \_replan() trong AgentSocietyHelper.\_run; chưa hỗ trợ DAG phụ thuộc.
- **Đáp ứng yêu cầu** · Một phần. Hỗ trợ mẫu Plan-Execute và lập kế hoạch/lập kế hoạch lại cho tương tác môi trường và can thiệp xã hội. [EV-002](#EV-002) [EV-018](#EV-018) [EV-022](#EV-022)

### C6 · Điều phối nhiều tác tử

- **Mức trưởng thành** · 3/4 · Áp dụng · Đã triển khai.
- **Xác minh** · Mã nguồn Đã xác minh. Thực thi Chưa xác minh. Tin cậy Cao.
- **Thực thi đã khảo sát** · Chưa xác minh runtime
- **Cơ chế** · AgentSociety tách driver khỏi đối tượng agent, fan-out step\_agent\_batch/questionnaire\_agent\_batch theo batch\_size=256, và điều phối truy cập EnvRouterActor theo cờ is\_concurrency\_safe (max\_concurrency=64 hoặc 1). Điểm trừ: chưa có giao thức nhắn tin trực tiếp giữa các agent ngoài env module; set\_current\_time/set\_replay\_writer trên proxy là fire-and-forget. [EV-013](#EV-013) [EV-019](#EV-019) [EV-020](#EV-020) [EV-030](#EV-030) [EV-037](#EV-037)
- **Giới hạn** · Các lệnh đồng bộ thời gian/replay tới EnvRouterActor là fire-and-forget không chờ xác nhận.
- **Đáp ứng yêu cầu** · Đáp ứng. Điều phối đồng thời quy mô lớn nhiều Silicon Participants qua Ray runtime và môi trường dùng chung. [EV-002](#EV-002) [EV-013](#EV-013) [EV-020](#EV-020)

### C7 · Tri thức và RAG

- **Mức trưởng thành** · 2/4 · Áp dụng · Một phần.
- **Xác minh** · Mã nguồn Đã xác minh. Thực thi Chưa xác minh. Tin cậy Vừa.
- **Thực thi đã khảo sát** · Chưa xác minh runtime
- **Cơ chế** · FAISS IndexFlatIP được dùng làm template cache trong CodeGenRouter; skills/literature tìm bài báo qua MCP và lưu papers/ + literature\_index.json; PersonAgent chỉ tìm kiếm từ khóa cục bộ trên episodes.jsonl. Chưa có pipeline RAG có rerank/citation/freshness nối vào vòng lặp PersonAgent; literature\_index.json ghi không atomic. [EV-011](#EV-011) [EV-015](#EV-015) [EV-027](#EV-027)
- **Giới hạn** · Thiếu kết nối retrieval/RAG có kiểm soát vào vòng lặp tác tử mô phỏng; ghi literature\_index.json không nguyên tử.
- **Đáp ứng yêu cầu** · Một phần. Hỗ trợ truy xuất tài liệu học thuật và tái sử dụng mẫu/tri thức trong nghiên cứu và mô phỏng. [EV-002](#EV-002) [EV-015](#EV-015) [EV-027](#EV-027)

### C8 · Kiểm chứng và tự sửa

- **Mức trưởng thành** · 3/4 · Áp dụng · Đã triển khai.
- **Xác minh** · Mã nguồn Đã xác minh. Thực thi Chưa xác minh. Tin cậy Cao.
- **Thực thi đã khảo sát** · Chưa xác minh runtime (chưa chạy pytest)
- **Cơ chế** · Mạnh ở tầng thiết kế tĩnh (AgentBase schema retry, RouterBase Pydantic retry, CodeGenRouter AST + write\_attempted guard, Analysis Harness cổng 2 lớp + SHA-256) và có 77 (+3) tệp pytest. Tuy nhiên chưa chạy được 0/77 tệp pytest trong môi trường kiểm toán và script\_generator.py đang tự mâu thuẫn với compatibility.py về constructor không tham số. [EV-005](#EV-005) [EV-014](#EV-014) [EV-015](#EV-015) [EV-023](#EV-023) [EV-029](#EV-029) [EV-034](#EV-034)
- **Giới hạn** · Chưa thực thi bộ 77 (+3) pytest cục bộ; lỗi mâu thuẫn constructor trong SafeModuleTester (script\_generator.py).
- **Đáp ứng yêu cầu** · Một phần. Đảm bảo đầu ra có cấu trúc, chống lỗi sinh code và có cổng kiểm chứng độc lập cho quy trình phân tích. [EV-002](#EV-002) [EV-015](#EV-015) [EV-023](#EV-023)

### C9 · An toàn và quản trị

- **Mức trưởng thành** · 2/4 · Áp dụng · Một phần.
- **Xác minh** · Mã nguồn Đã xác minh. Thực thi Test có fixture. Tin cậy Cao.
- **Thực thi đã khảo sát** · Đã kiểm fixture cô lập cho WorkspaceFS và path\_security
- **Cơ chế** · WorkspaceFS chặn thoát thư mục + .runtime/, \_is\_core\_owned\_workspace\_path bảo vệ tệp lõi, CodeGenRouter có AST guard + Linux process sandbox (prctl/RLIMIT), skill\_worker lọc biến môi trường, cache\_integrity ký HMAC-SHA256, backend có Auth/Origin/TrustedHost/path\_security. Tuy nhiên routers/custom.py chạy importlib exec\_module in-process trong FastAPI, skill upload không quét tĩnh, CodeGen non-Linux chạy inprocess, và Auth không có RBAC / lỗi phản hồi WS. [EV-006](#EV-006) [EV-008](#EV-008) [EV-009](#EV-009) [EV-015](#EV-015) [EV-016](#EV-016) [EV-028](#EV-028) [EV-029](#EV-029) [EV-031](#EV-031) [EV-033](#EV-033) [EV-036](#EV-036)
- **Giới hạn** · Thực thi mã tùy chỉnh in-process trong FastAPI backend; thiếu sandbox tiến trình trên Windows/macOS; không có RBAC.
- **Đáp ứng yêu cầu** · Một phần. Thực thi an toàn code sinh bởi LLM, custom skills/modules và API quản trị cục bộ. [EV-002](#EV-002) [EV-016](#EV-016) [EV-028](#EV-028) [EV-029](#EV-029)

### C10 · Quan sát và đánh giá

- **Mức trưởng thành** · 2/4 · Áp dụng · Một phần.
- **Xác minh** · Mã nguồn Đã xác minh. Thực thi Chưa xác minh. Tin cậy Cao.
- **Thực thi đã khảo sát** · Chưa xác minh runtime
- **Cơ chế** · JsonlTraceWriter truyền trace\_id/span\_id xuyên Ray actor, ReplaySink ghi 256 shard JSONL, LLMClient tổng hợp token vào LLM\_STATS.json. Điểm trừ: không có theo dõi chi phí USD, AgentBase span thiếu output\_tokens, RouterBase.\_llm\_completion\_span thiếu toàn bộ trường token, ShardedAppendSink thiếu file lock Windows và nuốt OSError không đếm drop, env/benchmark.py chỉ là DTO 13 dòng chưa có benchmark runner tự động. [EV-005](#EV-005) [EV-014](#EV-014) [EV-024](#EV-024) [EV-025](#EV-025) [EV-026](#EV-026) [EV-038](#EV-038)
- **Giới hạn** · Thiếu USD cost, thiếu token trên trace span (đặc biệt 100% ở RouterBase), không đếm drop trace khi OSError và thiếu benchmark runner.
- **Đáp ứng yêu cầu** · Một phần. Cung cấp replay phân tán, truy vết đầy đủ và theo dõi hiệu năng/tài nguyên mô phỏng. [EV-002](#EV-002) [EV-024](#EV-024) [EV-025](#EV-025) [EV-026](#EV-026)

### C11 · Tin cậy và mở rộng

- **Mức trưởng thành** · 3/4 · Áp dụng · Một phần.
- **Xác minh** · Mã nguồn Đã xác minh. Thực thi Chưa xác minh. Tin cậy Cao.
- **Thực thi đã khảo sát** · Chưa xác minh runtime
- **Cơ chế** · Ray Tasks không trạng thái, AdaptiveSemaphore AIMD, max\_retries=0 tránh lặp side-effect, SOCIETY\_STEP.json phát hiện crash bằng pending\_update. Điểm trừ: AGENTSOCIETY\_SHARED\_LLM\_QUOTA dùng fcntl trực tiếp gây crash trên Windows và dễ leak slot khi SIGKILL; ReplaySink.\_fds không có eviction; process sandbox chỉ chạy trên Linux. [EV-013](#EV-013) [EV-016](#EV-016) [EV-019](#EV-019) [EV-020](#EV-020) [EV-024](#EV-024) [EV-025](#EV-025) [EV-026](#EV-026)
- **Giới hạn** · Shared LLM quota không tương thích Windows và có rủi ro leak slot khi SIGKILL; ReplaySink.\_fds không giới hạn số fd mở.
- **Đáp ứng yêu cầu** · Một phần. Vận hành mô phỏng quy mô lớn tin cậy, kiểm soát tải LLM và phục hồi an toàn sau gián đoạn. [EV-002](#EV-002) [EV-013](#EV-013) [EV-020](#EV-020) [EV-024](#EV-024)

### C12 · Độc lập model

- **Mức trưởng thành** · 3/4 · Áp dụng · Đã triển khai.
- **Xác minh** · Mã nguồn Đã xác minh. Thực thi Chưa xác minh. Tin cậy Cao.
- **Thực thi đã khảo sát** · Chưa xác minh runtime
- **Cơ chế** · LiteLLM Router tách vai trò default/coder/embedding, hỗ trợ openai Chat Completions và anthropic Messages, chuẩn hóa thinking/reasoning\_effort, có text-parsed tool call fallback. Điểm trừ: LLMClient.\_build\_router chỉ đăng ký 1 model (không có fallback chain như Config.get\_router('coder')); nhiều trường Config đọc tĩnh lúc import. [EV-003](#EV-003) [EV-004](#EV-004) [EV-005](#EV-005) [EV-024](#EV-024)
- **Giới hạn** · LLMClient chưa hỗ trợ fallback chain giữa các model/provider khi gặp lỗi kéo dài.
- **Đáp ứng yêu cầu** · Đáp ứng. Hỗ trợ linh hoạt nhiều nhà cung cấp LLM (OpenAI/Anthropic/tương thích) và cấu hình theo vai trò. [EV-002](#EV-002) [EV-024](#EV-024)

## Công nghệ và tích hợp

- **litellm 1.103.10** · LLMClient.\_build\_router và Config.get\_router cho default/coder/embedding. active. Model SDK / Router đa nhà cung cấp (OpenAI, Anthropic) [EV-003](#EV-003) [EV-004](#EV-004) [EV-024](#EV-024)
- **ray 2.58.0** · step\_agent\_batch, questionnaire\_agent\_batch và EnvRouterActor (chỉ cài khi sys\_platform != win32). active\_non\_win32. Runtime thực thi phân tán (Tasks cho agent batches, Actor cho EnvRouter) [EV-003](#EV-003) [EV-004](#EV-004) [EV-013](#EV-013) [EV-019](#EV-019)
- **mcp 2.3.0** · EnvBase chỉ dùng mcp Tool/ToolManager làm JSON Schema builder nội bộ; giao thức MCP thực tế nằm ở skills/literature/mcp\_client.py (Streamable HTTP client) và extension/src/services/mcpClient.ts (HTTP JSON-RPC + SSE probe). active\_partial. Model Context Protocol SDK (ToolManager nội bộ + Streamable HTTP client) [EV-003](#EV-003) [EV-004](#EV-004) [EV-027](#EV-027) [EV-037](#EV-037)
- **faiss-cpu 1.15.1** · CodeGenRouter TemplateCacheDB (IndexFlatIP) — không dùng làm RAG cho agent. active. Chỉ mục vector tìm kiếm tương đồng cho CodeGen template cache [EV-003](#EV-003) [EV-004](#EV-004) [EV-015](#EV-015)
- **pydantic 2.13.5** · RouterBase.acompletion\_with\_pydantic\_validation, AgentMemoryStore, Analysis Harness models. active. Xác thực schema dữ liệu, cấu hình, memory episodes và kết quả LLM [EV-004](#EV-004) [EV-014](#EV-014) [EV-023](#EV-023)
- **mem0ai 2.1.0** · Chỉ import ở 1 contrib agent (llm\_donor\_agent.py), không dùng trong PersonAgent. contrib\_only. Thư viện quản lý bộ nhớ tác tử (khai báo dependency lõi nhưng không nằm trong đường chạy chính) [EV-003](#EV-003) [EV-004](#EV-004) [EV-012](#EV-012)

### LLM Providers (OpenAI / Anthropic compatible)

Suy luận cho PersonAgent, CodeGenRouter, AgentSocietyHelper và memory consolidation [EV-024](#EV-024)
- **Ranh giới** · HTTP/HTTPS qua LiteLLM Router (AGENTSOCIETY\_LLM\_API\_BASE)
- **Xác thực** · API key qua biến môi trường AGENTSOCIETY\_\[CODER\_\]LLM\_API\_KEY
- **Lỗi** · Timeout 60s, max\_retries=3, fail-fast context limit, backoff mũ 429, AdaptiveSemaphore AIMD
- **Runtime** · Chưa kiểm chứng runtime (không có API key trong môi trường audit)

### Literature MCP Gateway

Tìm kiếm và nạp tài liệu học thuật cho research workflow [EV-027](#EV-027)
- **Ranh giới** · Streamable HTTP MCP client tới LITERATURE\_SEARCH\_MCP\_URL (mặc định https://llmapi.fiblab.net/mcp/)
- **Xác thực** · Bearer token tùy chọn qua LITERATURE\_SEARCH\_API\_KEY
- **Lỗi** · Timeout 120s (list\_tools 30/300s), kiểm tra is\_error ngoài async with, không có retry
- **Runtime** · Chưa kiểm chứng runtime

### External AI Coding Agents (Claude Code / Codex / Cursor)

Tác tử nghiên cứu bên ngoài điều phối qua VS Code extension và Analysis Harness CLI [EV-023](#EV-023) [EV-030](#EV-030)
- **Ranh giới** · VS Code commands, ~/.claude.json MCP config và Analysis Harness CLI JSON/YAML artifacts
- **Xác thực** · Quản lý bởi IDE/CLI bên ngoài
- **Lỗi** · Cưỡng chế qua exit code 0/1/2 và phase gates của Analysis Harness
- **Runtime** · Ngoài phạm vi thực thi của kho mã

## Phát hiện, cơ chế và phản chứng

<a id="finding-F-001"></a>

### F-001 · Kiến trúc Agent Harness phân lớp, tối ưu prompt-prefix cache và tách biệt trạng thái tốt

- **Loại nhận định** · Sự kiện đã đối chiếu
- **Quan sát** · AgentBase/PersonAgent sở hữu trọn vẹn vòng lặp ReAct append-only không cắt đầu, json\_block sort\_keys=True, làm mới ngữ cảnh chọn lọc, và kiến trúc stateless Ray Tasks tách bộ nhớ driver khỏi số lượng tác tử N. [EV-005](#EV-005) [EV-007](#EV-007) [EV-008](#EV-008) [EV-013](#EV-013) [EV-020](#EV-020)
- **Cơ chế** · Thread ReAct chỉ nối thêm tin nhắn trong suốt một step và tách khối hệ thống bất biến khỏi trạng thái biến thiên theo lượt; AgentSociety chỉ giữ agent\_specs và phục dựng agent từ đĩa trong mỗi Ray Task.
- **Ảnh hưởng** · Tăng tỷ lệ trúng prompt-prefix cache, tránh phình RAM ở driver khi mô phỏng quy mô lớn và bảo đảm tính bền vững trạng thái trên đĩa.
- **Phản chứng và giới hạn** · Nếu một step kéo dài nhiều lượt với observation lớn, việc cấm cắt đầu thread có thể đẩy ngữ cảnh chạm giới hạn cửa sổ model (context limit fail-fast).
- **Trạng thái kiểm chứng** · Đã xác minh qua mã nguồn (agent.py, person\_prompt.py, runner.py); cần chạy benchmark E2E để đo tỷ lệ cache hit thực tế.
- **Luồng liên quan** · [FLOW-01](#flow-FLOW-01) [FLOW-03](#flow-FLOW-03)
<a id="finding-F-002"></a>

### F-002 · Cơ chế cổng 2 lớp và chống stale bằng SHA-256 trong Analysis Harness

- **Loại nhận định** · Sự kiện đã đối chiếu
- **Quan sát** · Analysis Harness tách bạch hoàn toàn lớp cơ học xác định (0 lời gọi LLM) khỏi lớp phán đoán của AI agent bên ngoài, cưỡng chế thứ tự pha, xác nhận độc lập và trải nghiệm bộ nhớ 4 bước có kiểm soát. [EV-023](#EV-023)
- **Cơ chế** · Mỗi chuyển pha đều kiểm tra structural validator, rubric attestation, và đối chiếu SHA-256 fingerprint của artifact trước khi cho phép advance hoặc release.
- **Ảnh hưởng** · Ngăn AI agent bên ngoài nhảy cóc bước, tự chấm đỗ hoặc chỉnh sửa báo cáo sau khi đã qua phản biện.
- **Phản chứng và giới hạn** · Vì tầng phán đoán vẫn do AI agent ngoài điền vào PhaseAttestation, một agent không trung thực vẫn có thể điền rubric hình thức nếu structural validator không phủ hết ngữ nghĩa.
- **Trạng thái kiểm chứng** · Đã xác minh qua đọc toàn bộ 29 tệp trong skills/analysis/harness/; cần chạy test\_harness\_guardrails.py trong môi trường đủ dependency.
- **Luồng liên quan** · [FLOW-04](#flow-FLOW-04)
<a id="finding-F-003"></a>

### F-003 · Backend và ModuleRegistry thực thi mã custom in-process không sandbox; lỗi contract test và upload skill không quét tĩnh

- **Loại nhận định** · Rủi ro
- **Quan sát** · FastAPI endpoints (/custom/scan, /custom/test, /custom/list, /modules/agent\_classes) và registry/modules.py:\_load\_custom\_class() chạy importlib exec\_module trực tiếp in-process (scanner.py:L245, script\_generator.py:L102, registry/modules.py:L51); script\_generator.py:L183,L407 gọi cls(id=0, profile=...) mâu thuẫn với compatibility.py yêu cầu \_\_init\_\_() không tham số; upload/create skill không quét tĩnh mã nguồn. [EV-028](#EV-028) [EV-029](#EV-029) [EV-036](#EV-036)
- **Cơ chế** · CustomModuleScanner (scanner.py:L245), SafeModuleTester (script\_generator.py:L102) và ModuleRegistry.\_load\_custom\_class (registry/modules.py:L51) đều gọi spec.loader.exec\_module() trong tiến trình chính; khi không đặt BACKEND\_TOKEN, mọi tiến trình local đều gọi được API. Lưu ý: toàn bộ backend/routers/ hiện có 0 WebSocket routes nên lỗi JSONResponse ở app.py:L199,L214 chỉ là phòng thủ.
- **Ảnh hưởng** · Mã độc hoặc mã lỗi trong thư mục custom/ của workspace có thể thực thi tùy ý với quyền và biến môi trường (kể cả API key) của tiến trình Backend.
- **Phản chứng và giới hạn** · Backend mặc định chỉ bind 127.0.0.1, có BrowserOriginMiddleware/TrustedHostMiddleware và giới hạn workspace qua WORKSPACE\_PATH, nên rủi ro chủ yếu đến từ workspace không tin cậy hoặc tiến trình cục bộ khác.
- **Trạng thái kiểm chứng** · Đã xác minh trực tiếp qua đọc mã nguồn app.py, routers/custom.py, scanner.py, script\_generator.py và agent\_skills.py.
- **Khuyến nghị và nghiệm thu** · [REC-01](#rec-REC-01)
<a id="finding-F-004"></a>

### F-004 · Lỗi logic chỉ số bước sau khi replan trong AgentSocietyHelper.\_run()

- **Loại nhận định** · Giả thuyết
- **Quan sát** · Khi \_replan() trả về kế hoạch mới (chỉ chứa các bước còn lại theo prompt 'DO NOT repeat SUCCESS steps'), \_run() vẫn lấy step\_index = len(execution\_history) đối chiếu với len(plan): nếu new\_plan ngắn hơn/bằng sẽ thoát sớm, còn nếu dài hơn sẽ nhảy cóc phần đầu new\_plan. Tệp tests/test\_society\_helper\_xml.py chưa có test nào cho \_run() hay \_replan(). [EV-022](#EV-022)
- **Cơ chế** · Prompt replan cấm lặp bước đã thành công (helper.py:L724), nhưng \_run() gán plan = new\_plan (L224) trong khi giữ step\_index = len(execution\_history) (L180-L183). Do đó cả 2 trường hợp len(new\_plan) &lt;= len(execution\_history) (thoát sớm) lẫn len(new\_plan) &gt; len(execution\_history) (nhảy cóc bước đầu) đều sai lệch so với hợp đồng prompt.
- **Ảnh hưởng** · Các truy vấn ask()/intervene() gặp lỗi giữa chừng và kích hoạt replan có thể kết thúc thiếu bước thực thi, dẫn đến câu trả lời sai hoặc thiếu dữ liệu.
- **Phản chứng và giới hạn** · Nếu LLM bỏ qua hướng dẫn prompt và lặp lại cả các bước cũ trong new\_plan sao cho len(new\_plan) &gt; len(execution\_history), lỗi thoát sớm sẽ không kích hoạt nhưng lại có nguy cơ chạy lệch bước.
- **Trạng thái kiểm chứng** · Cần viết và chạy unit test mô phỏng \_replan() trả về 1 bước mới khi execution\_history đã có 2 bước (dự kiến xác nhận thoát sớm ở L181).
- **Khuyến nghị và nghiệm thu** · [REC-02](#rec-REC-02)
<a id="finding-F-005"></a>

### F-005 · Khoảng trống tương thích Windows và cô lập tiến trình (CodeGen sandbox, shared LLM quota, trace lock)

- **Loại nhận định** · Rủi ro
- **Quan sát** · Process sandbox của CodeGenRouter chỉ hỗ trợ Linux (non-Linux chạy inprocess không giới hạn RAM OS); AGENTSOCIETY\_SHARED\_LLM\_QUOTA gọi import fcntl trực tiếp gây crash trên Windows; ShardedAppendSink không khóa tệp liên tiến trình trên Windows. [EV-016](#EV-016) [EV-024](#EV-024) [EV-025](#EV-025)
- **Cơ chế** · codegen\_process.py:L226 chặn sys.platform != 'linux'; llm\_dispatcher.py:L88 import fcntl không có fallback msvcrt; sharded\_writer.py:L32 đặt fcntl=None trên Windows.
- **Ảnh hưởng** · Trên Windows/macOS, code sinh bởi LLM không có bảo vệ RLIMIT\_AS/killpg, bật shared quota sẽ gây ModuleNotFoundError, và ghi trace đa tiến trình có nguy cơ xen kẽ dòng.
- **Phản chứng và giới hạn** · Tài liệu pyproject.toml và CLAUDE.md định vị production scale (Ray + process sandbox) chủ yếu trên Linux, nên một phần giới hạn trên Windows có thể là đánh đổi có chủ đích cho môi trường dev.
- **Trạng thái kiểm chứng** · Đã xác minh qua mã nguồn; có thể kiểm nhanh bằng việc bật AGENTSOCIETY\_SHARED\_LLM\_QUOTA=2 trên Windows.
- **Luồng liên quan** · [FLOW-02](#flow-FLOW-02) [FLOW-03](#flow-FLOW-03)
- **Khuyến nghị và nghiệm thu** · [REC-03](#rec-REC-03)
<a id="finding-F-006"></a>

### F-006 · ReActRouter và TwoTierReActRouter đều bỏ truyền tools từ bước 2; LLMClient không cấu hình fallback chain

- **Loại nhận định** · Rủi ro
- **Quan sát** · Cả ReActRouter.ask() (L176-L187) và TwoTierReActRouter.\_react\_with\_module() (L380-L391) chỉ truyền tools khi step==1 và đặt tools=None ở các bước sau (khác với SearchToolRouter truyền tools ở mọi bước). Riêng LLMClient.\_build\_router chọn 1 model và num\_retries=0 để kiểm soát backoff tập trung tại AdaptiveSemaphore (đánh đổi có chủ đích, thiếu fallback đa provider). [EV-017](#EV-017) [EV-024](#EV-024) [EV-035](#EV-035)
- **Cơ chế** · Hai router ReAct đặt điều kiện step == 1 trước khi gán call\_kwargs\['tools'\]; trong khi LLMClient bỏ fallback ở tầng LiteLLM Router để giữ quyền điều tiết AIMD tập trung (khác với đường helper cũ Config.get\_router).
- **Ảnh hưởng** · ReActRouter có thể mất khả năng gọi tool từ lượt thứ 2 trở đi trên các provider OpenAI-compatible chuẩn; khi 1 endpoint LLM gặp sự cố kéo dài, simulation fail thay vì chuyển sang model dự phòng.
- **Phản chứng và giới hạn** · Mặc định hệ thống dùng CodeGenRouter nên ReActRouter ít nằm trên đường chạy chính; việc LLMClient không dùng LiteLLM retry giúp kiểm soát backoff/quota tập trung tại AdaptiveSemaphore.
- **Trạng thái kiểm chứng** · Cần chạy test tích hợp trên ReActRouter với kịch bản cần 2 lần gọi tool liên tiếp.
- **Luồng liên quan** · [FLOW-02](#flow-FLOW-02)
- **Khuyến nghị và nghiệm thu** · [REC-04](#rec-REC-04)
<a id="finding-F-007"></a>

### F-007 · Thiếu chi phí USD, thiếu token trên trace span (AgentBase &amp; RouterBase), không đếm drop trace và MCP client mở 2 phiên

- **Loại nhận định** · Sự kiện đã đối chiếu
- **Quan sát** · SDK chưa tính chi phí USD; AgentBase.\_record\_llm\_usage thiếu output\_tokens; RouterBase.\_llm\_completion\_span (L309-L314) thiếu toàn bộ trường token; ShardedAppendSink nuốt OSError không tăng bộ đếm drop; env/benchmark.py chỉ là DTO 13 dòng chưa có benchmark harness tự động; skills/literature/mcp\_client.py mở 2 phiên HTTP/MCP liên tiếp cho mỗi lần gọi mà không có retry. [EV-005](#EV-005) [EV-024](#EV-024) [EV-025](#EV-025) [EV-027](#EV-027) [EV-038](#EV-038)
- **Cơ chế** · LLMClient chỉ cộng dồn số token mà không quy đổi chi phí; AgentBase.\_record\_llm\_usage chỉ ghi input/cached\_input/cache\_hit\_rate; call\_literature\_mcp\_tool gọi \_list\_literature\_tool\_names rồi mở session thứ 2 để call\_tool.
- **Ảnh hưởng** · Khó kiểm soát ngân sách mô phỏng quy mô lớn theo từng bước/tác tử và tăng gấp đôi độ trễ khởi tạo kết nối khi tìm kiếm tài liệu qua MCP.
- **Phản chứng và giới hạn** · LITELLM\_LOCAL\_MODEL\_COST\_MAP=True được bật để tránh gọi mạng tải bảng giá, phản ánh ưu tiên chạy offline/nội bộ hơn là tính giá tự động.
- **Trạng thái kiểm chứng** · Đã xác minh trực tiếp qua mã nguồn llm\_dispatcher.py, agent.py và mcp\_client.py.
- **Luồng liên quan** · [FLOW-01](#flow-FLOW-01)
- **Khuyến nghị và nghiệm thu** · [REC-05](#rec-REC-05)
<a id="finding-F-008"></a>

### F-008 · Lệch giữa dependency khai báo (mem0ai, tiktoken) với đường gọi thực tế và giới hạn fd ở ReplaySink

- **Loại nhận định** · Sự kiện đã đối chiếu
- **Quan sát** · mem0ai và tiktoken nằm trong dependencies lõi của pyproject.toml nhưng PersonAgent không sử dụng (mem0ai chỉ có ở 1 contrib agent); ReplaySink.\_fds cache file descriptor không giới hạn eviction. [EV-003](#EV-003) [EV-004](#EV-004) [EV-011](#EV-011) [EV-012](#EV-012) [EV-026](#EV-026)
- **Cơ chế** · PersonAgent tự quản lý bộ nhớ bằng AgentMemoryStore (MEMORY.md + episodes.jsonl); ReplaySink mở dần tới 256 shard/bảng trong self.\_fds mà không có chính sách FIFO eviction như ShardedAppendSink (64 fd).
- **Ảnh hưởng** · Tăng kích thước cài đặt và bề mặt phụ thuộc thừa; mô phỏng có nhiều bảng replay trên hệ thống giới hạn ulimit -n thấp có thể gặp lỗi cạn file descriptor.
- **Phản chứng và giới hạn** · Giữ mem0ai trong dependencies chính giúp các contrib agent (llm\_donor\_agent) chạy không cần cài extra; với số bảng replay nhỏ (&lt;4 bảng), 256 shard vẫn dưới ngưỡng ulimit mặc định trên Linux.
- **Trạng thái kiểm chứng** · Đã xác minh qua grep toàn bộ mã nguồn agentsociety2 và đọc replay\_sink.py.
- **Luồng liên quan** · [FLOW-03](#flow-FLOW-03)
- **Khuyến nghị và nghiệm thu** · [REC-06](#rec-REC-06)
<a id="finding-F-009"></a>

### F-009 · Chưa xác minh hành vi đầu-cuối (E2E), bộ 77 (+3) pytest và hiệu năng thực tế trên Ray cluster

- **Loại nhận định** · Giả thuyết
- **Quan sát** · Do môi trường kiểm toán cục bộ không có uv/.venv, thiếu các gói runtime (litellm, ray, faiss, mcp, duckdb, pytest) và không có LLM API key, toàn bộ 4 luồng đại diện mới chỉ dừng ở xác minh tĩnh và 3 fixture cô lập (0/77 tệp pytest trong agentsociety2/tests/ được thực thi). [EV-031](#EV-031) [EV-032](#EV-032) [EV-033](#EV-033) [EV-034](#EV-034)
- **Cơ chế** · Thiếu môi trường chạy đã khóa (uv sync --locked) và thông tin xác thực LLM/MCP khiến không thể kích hoạt simulation loop, Ray actor concurrency hay Linux codegen worker.
- **Ảnh hưởng** · Không thể kết luận Mức 4 hay khẳng định không có lỗi tích hợp/hồi quy lúc chạy thực tế; độ phủ E2E hiện là 0%.
- **Phản chứng và giới hạn** · Kho mã có sẵn 46 tệp pytest và CI scope rõ ràng (AGENTS.md), cho thấy các bài kiểm thử tự động có thể chạy được ngay khi cung cấp đủ môi trường uv trên Linux.
- **Trạng thái kiểm chứng** · Cần chạy \`uv sync --locked --package agentsociety2 --no-default-groups --extra dev &amp;&amp; cd packages/agentsociety2 &amp;&amp; uv run pytest\` cùng 1 kịch bản mô phỏng mẫu có LLM mock/thật trên Linux.
- **Luồng liên quan** · [FLOW-01](#flow-FLOW-01) [FLOW-02](#flow-FLOW-02) [FLOW-03](#flow-FLOW-03) [FLOW-04](#flow-FLOW-04)
- **Khuyến nghị và nghiệm thu** · [REC-06](#rec-REC-06)

## Rủi ro và phép kiểm

- **RISK-01 · Thực thi mã tùy ý trong tiến trình FastAPI Backend khi scan/test custom module** · Tác động high. Khả năng medium. CustomModuleScanner và SafeModuleTester nạp trực tiếp file .py trong workspace bằng exec\_module in-process; nếu mở workspace từ nguồn không tin cậy hoặc gọi API từ tiến trình cục bộ khác khi không đặt BACKEND\_TOKEN, mã độc chạy với toàn quyền tiến trình backend. [EV-028](#EV-028) [EV-029](#EV-029)
- **RISK-02 · Thoát vòng lặp replan sớm trong AgentSocietyHelper làm sai lệch kết quả ask/intervene** · Tác động medium. Khả năng medium. Do step\_index không được reset hoặc cộng bù sau khi thay plan mới bằng \_replan(), các bước phục hồi mới có thể bị bỏ qua hoàn toàn. [EV-022](#EV-022)
- **RISK-03 · Rủi ro ổn định và cô lập khi chạy trên Windows/macOS** · Tác động medium. Khả năng high. CodeGenRouter fallback sang inprocess (không có RLIMIT\_AS/killpg), shared LLM quota crash do thiếu fcntl, và trace writer không khóa file liên tiến trình trên Windows. [EV-016](#EV-016) [EV-024](#EV-024) [EV-025](#EV-025)
- **RISK-04 · Mất kiểm soát chi phí LLM và khó chẩn đoán token đầu ra trên mô phỏng lớn** · Tác động medium. Khả năng medium. Thiếu tính toán chi phí USD, thiếu output\_tokens trên trace span và thiếu token budget chủ động trước khi gọi LLM. [EV-005](#EV-005) [EV-024](#EV-024) [EV-025](#EV-025)
- **RISK-05 · Rò rỉ slot shared quota khi SIGKILL và cạn file descriptor ở ReplaySink** · Tác động medium. Khả năng low. Process chết đột ngột (SIGKILL) không nhả slot trong tệp shared quota; ReplaySink.\_fds giữ vô hạn fd đã mở theo shard/bảng. [EV-024](#EV-024) [EV-026](#EV-026)

### Kiểm tra fixture cô lập WorkspaceFS (ghi/chặn .runtime/chặn path escape)

- **Môi trường** · Windows, Python 3.13.15, TemporaryDirectory (không sửa mã nguồn)
- **Kết quả** · PASS: write\_ok=True, runtime\_blocked=True, escape\_blocked=True [EV-031](#EV-031)
- **Giới hạn** · Chỉ xác minh module WorkspaceFS độc lập, không thay thế kiểm thử E2E.

### Kiểm tra fixture cô lập AgentMemoryStore (khởi tạo MEMORY.md)

- **Môi trường** · Windows, Python 3.13.15, TemporaryDirectory
- **Kết quả** · PASS: memory\_md\_exists=True, md\_len=283 [EV-032](#EV-032)
- **Giới hạn** · Chỉ xác minh lưu trữ cục bộ, chưa gọi LLM consolidation.

### Kiểm tra fixture cô lập Backend path\_security (chặn traversal)

- **Môi trường** · Windows, Python 3.13.15, TemporaryDirectory
- **Kết quả** · PASS: root\_matched=True, traversal\_blocked=True [EV-033](#EV-033)
- **Giới hạn** · Chưa kiểm tra toàn bộ ứng dụng FastAPI và WebSocket.

### Kiểm tra khả năng chạy bộ 77 (+3) pytest &amp; Analysis Harness CLI cục bộ

- **Môi trường** · Windows, Python 3.13.15 (chưa cài uv/.venv)
- **Kết quả** · BLOCKED: thiếu pytest, litellm, ray, faiss-cpu, mcp, duckdb trong môi trường Python toàn cục [EV-034](#EV-034)
- **Giới hạn** · Không thể chạy xác minh E2E hay hồi quy tự động trong phiên kiểm toán này.
- **Tập luồng đại diện** · [FLOW-01](#flow-FLOW-01) [FLOW-02](#flow-FLOW-02) [FLOW-03](#flow-FLOW-03) [FLOW-04](#flow-FLOW-04)
- **Luồng đã kiểm chứng đầu-cuối** · Chưa có.

## Bài học rút ra từ phân tích nguyên nhân gốc rễ

- **Không đánh đồng dependency khai báo trong pyproject.toml với đường chạy thực tế** · mem0ai được khai báo ở dependencies lõi của agentsociety2 nhưng PersonAgent không hề import; việc kiểm chứng bằng grep và truy vết đường gọi giúp tránh kết luận sai về kiến trúc bộ nhớ. [EV-003](#EV-003) [EV-011](#EV-011) [EV-012](#EV-012)
- **Tách rõ deterministic harness khỏi LLM agent bên ngoài** · Analysis Harness có đầy đủ phase gates, attestation và experience memory nhưng hoàn toàn không gọi LLM (0 lời gọi trong 29 tệp) mà đóng vai trò rào kiểm soát cho AI agent bên ngoài. [EV-023](#EV-023) [EV-030](#EV-030)

## Khuyến nghị và lộ trình

<a id="rec-REC-01"></a>

### REC-01 · Cách ly việc scan/test custom module khỏi tiến trình FastAPI và sửa xử lý WebSocket auth

**P0 · Pha 1 · Gia cố bảo mật &amp; sửa lỗi đúng đắn · M**

- **Vấn đề** · CustomModuleScanner (scanner.py:L245), SafeModuleTester (script\_generator.py:L102) và registry/modules.py:\_load\_custom\_class (L51) chạy exec\_module in-process trong FastAPI; script\_generator.py mâu thuẫn với compatibility.py về constructor không tham số; BackendAuthMiddleware trả JSONResponse cho scope WS (dù hiện có 0 WS routes). [EV-028](#EV-028) [EV-029](#EV-029) [EV-036](#EV-036)
- **Ảnh hưởng** · Loại bỏ bề mặt thực thi mã không tin cậy trong tiến trình Backend và chuẩn hóa đóng kết nối WebSocket.
- **Cách xử lý** · Chuyển toàn bộ đường nạp/scan/test custom module (kể cả registry/modules.py khi gọi từ Backend API) sang subprocess ngắn hạn với whitelist env vars, đồng bộ contract khởi tạo trong script\_generator.py với compatibility.py, và vệ sinh nhánh phòng thủ WS bằng websocket.close(code=1008).
- **Thành phần** · agentsociety2/backend/services/custom/, registry/modules.py &amp; backend/app.py
- **Tái sử dụng** · Tái sử dụng mẫu subprocess worker + ALLOWED\_ENV\_VARS của agent/base/skill\_worker.py.
- **Nghiệm thu** · POST /api/v1/custom/scan và /test chạy trong tiến trình con không kế thừa AGENTSOCIETY\_LLM\_API\_KEY; kiểm thử WebSocket không có token đóng kết nối sạch bằng mã 1008 thay vì lỗi ASGI.
- **Phát hiện** · [F-003](#finding-F-003)
<a id="rec-REC-02"></a>

### REC-02 · Sửa logic con trỏ bước sau khi replan trong AgentSocietyHelper.\_run()

**P1 · Pha 1 · Gia cố bảo mật &amp; sửa lỗi đúng đắn · S**

- **Vấn đề** · step\_index vẫn dùng len(execution\_history) sau khi thay plan = new\_plan, khiến vòng lặp thoát sớm khi kế hoạch mới chỉ chứa các bước còn lại. [EV-022](#EV-022)
- **Ảnh hưởng** · Bảo đảm cơ chế tự phục hồi replan của ask()/intervene() thực thi đủ các bước mới mà vẫn giữ trần max\_steps.
- **Cách xử lý** · Tách biến plan\_cursor (reset về 0 mỗi khi thay plan = new\_plan) khỏi tổng số bước đã chạy len(execution\_history) &lt; self.\_max\_steps.
- **Thành phần** · agentsociety2/society/helper.py
- **Tái sử dụng** · Áp dụng cách tách con trỏ vòng trong/ngoài tương tự PlanExecuteRouter.
- **Nghiệm thu** · Unit test với kịch bản lỗi ở bước 2 và \_replan() trả về 1 bước mới phải thực thi được bước mới đó thay vì break sớm.
- **Phát hiện** · [F-004](#finding-F-004)
<a id="rec-REC-03"></a>

### REC-03 · Khắc phục tương thích đa nền tảng cho shared quota, trace lock và cảnh báo sandbox

**P1 · Pha 2 · Tin cậy vận hành &amp; đa nền tảng · M**

- **Vấn đề** · Shared LLM quota gọi import fcntl trực tiếp gây crash trên Windows và dễ leak slot khi SIGKILL; ShardedAppendSink thiếu file lock trên Windows. [EV-016](#EV-016) [EV-024](#EV-024) [EV-025](#EV-025) [EV-026](#EV-026)
- **Ảnh hưởng** · Đảm bảo hoạt động ổn định trên Windows và tránh treo hàng đợi quota sau crash tiến trình.
- **Cách xử lý** · Tái sử dụng \_file\_lock đa nền tảng (fcntl/msvcrt) từ replay\_sink.py cho shared quota và trace writer; lưu danh sách PID+timestamp trong tệp quota để tự dọn slot của tiến trình đã chết.
- **Thành phần** · agentsociety2/config/llm\_dispatcher.py &amp; trace/sharded\_writer.py
- **Tái sử dụng** · Tái sử dụng trực tiếp \_file\_lock trong storage/replay\_sink.py.
- **Nghiệm thu** · Bật AGENTSOCIETY\_SHARED\_LLM\_QUOTA=2 chạy qua trên Windows không crash; khi kill -9 một worker giữ slot, worker khác tự thu hồi slot hợp lệ.
- **Phát hiện** · [F-005](#finding-F-005)
<a id="rec-REC-04"></a>

### REC-04 · Sửa truyền tools đa bước ở ReActRouter &amp; TwoTierReActRouter và bổ sung tùy chọn fallback model cho LLMClient

**P2 · Pha 2 · Tin cậy vận hành &amp; đa nền tảng · S**

- **Vấn đề** · Cả ReActRouter (L177) và TwoTierReActRouter (L381) bỏ tools từ bước &gt;=2; LLMClient chưa hỗ trợ fallback model tùy chọn. [EV-017](#EV-017) [EV-024](#EV-024) [EV-035](#EV-035)
- **Ảnh hưởng** · Đảm bảo ReActRouter gọi tool ổn định qua nhiều lượt và tăng độ sẵn sàng khi gọi LLM.
- **Cách xử lý** · Truyền tools nhất quán ở mọi bước của ReActRouter.ask(); cho phép LLMClient cấu hình danh sách model dự phòng tùy chọn qua biến môi trường.
- **Thành phần** · agentsociety2/env/router\_react.py, router\_two\_tier\_react.py &amp; config/llm\_dispatcher.py
- **Tái sử dụng** · Tận dụng cấu trúc fallback đã có trong Config.get\_router('coder').
- **Nghiệm thu** · Test ReActRouter gọi 2 tool liên tiếp đạt PASS; test LLMClient chuyển sang model dự phòng khi model chính trả 503 liên tục.
- **Phát hiện** · [F-006](#finding-F-006)
<a id="rec-REC-05"></a>

### REC-05 · Bổ sung token/cost đầy đủ trên trace (AgentBase &amp; RouterBase), đếm drop trace và gộp phiên Literature MCP client

**P2 · Pha 3 · Quan sát, dọn dẹp &amp; kiểm chứng E2E · S**

- **Vấn đề** · AgentBase thiếu output\_tokens, RouterBase.\_llm\_completion\_span thiếu 100% trường token, SDK chưa tính USD cost, ShardedAppendSink nuốt OSError không đếm drop, và mcp\_client.py mở 2 phiên HTTP/MCP mỗi lần gọi không retry. [EV-005](#EV-005) [EV-024](#EV-024) [EV-025](#EV-025) [EV-027](#EV-027) [EV-038](#EV-038)
- **Ảnh hưởng** · Minh bạch chi phí vận hành theo từng tác tử/bước và giảm một nửa độ trễ kết nối MCP.
- **Cách xử lý** · Ghi llm.output\_tokens và ước tính cost (từ bảng giá cấu hình cục bộ) vào span và token stats; gộp list\_tools + call\_tool vào cùng một ClientSession trong mcp\_client.py kèm retry có giới hạn.
- **Thành phần** · agentsociety2/agent/base/agent.py, env/router\_base.py, trace/sharded\_writer.py, skills/literature/mcp\_client.py
- **Tái sử dụng** · Mở rộng trực tiếp \_record\_llm\_usage và \_record\_tokens hiện có.
- **Nghiệm thu** · Trace JSONL xuất đầy đủ input/output/cached tokens và ước tính chi phí; mcp\_client chỉ mở 1 phiên ClientSession cho mỗi lời gọi.
- **Phát hiện** · [F-007](#finding-F-007)
<a id="rec-REC-06"></a>

### REC-06 · Dọn dependency dư thừa, giới hạn fd ở ReplaySink và chạy kiểm chứng E2E trên Linux

**P2 · Pha 3 · Quan sát, dọn dẹp &amp; kiểm chứng E2E · M**

- **Vấn đề** · mem0ai nằm ở dependency lõi dù chỉ dùng trong 1 contrib agent; ReplaySink.\_fds không có eviction; chưa có bằng chứng chạy pytest/E2E trên môi trường khóa. [EV-003](#EV-003) [EV-012](#EV-012) [EV-026](#EV-026) [EV-034](#EV-034)
- **Ảnh hưởng** · Giảm rủi ro cạn fd, gọn gói cài đặt và xác lập bằng chứng vận hành E2E để đánh giá tiến lên Mức 4.
- **Cách xử lý** · Chuyển mem0ai sang optional-dependencies (contrib), áp dụng FIFO eviction cho ReplaySink.\_fds tương tự ShardedAppendSink, và chạy bộ 46 pytest + 1 kịch bản mô phỏng E2E trên môi trường Linux đã uv sync.
- **Thành phần** · packages/agentsociety2/pyproject.toml, storage/replay\_sink.py, CI/Test environment
- **Tái sử dụng** · Tái sử dụng cơ chế FIFO fd cache từ trace/sharded\_writer.py.
- **Nghiệm thu** · 77 tệp pytest trong packages/agentsociety2/tests/ (+ 3 tệp daily\_mobility) PASS 100%, kiểm thử 4 luồng đại diện đạt E2E và ReplaySink giữ số fd mở dưới ngưỡng cấu hình.
- **Phụ thuộc** · [REC-01](#rec-REC-01) [REC-02](#rec-REC-02) [REC-03](#rec-REC-03)
- **Phát hiện** · [F-008](#finding-F-008) [F-009](#finding-F-009)

## Sổ bằng chứng

<a id="EV-001"></a>

### EV-001 · Active scope &amp; Key subsystems

- **Project và vị trí** · agentsociety2 · AGENTS.md · L1-L82
- **Phát hiện** · Xác định phạm vi active gồm packages/agentsociety2/, examples/v2/daily\_mobility/, extension/, frontend/; packages/agentsociety (v1) là legacy tham chiếu.
- **Vai trò** · Chốt phạm vi kiểm toán và ranh giới phân hệ active.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Tài liệu định hướng, cần đối chiếu với mã thực thi.
<a id="EV-002"></a>

### EV-002 · AgentSociety 2 Features &amp; Architecture

- **Project và vị trí** · agentsociety2 · README.md · L59-L116
- **Phát hiện** · Công bố yêu cầu sản phẩm: nền tảng mô phỏng tác tử LLM-native, nhiều router (CodeGen/ReAct/Plan-Execute/Two-Tier/Search), Ray runtime, Research Skills, Replay JSONL+DuckDB, hỗ trợ MCP.
- **Vai trò** · Nguồn xác lập tiêu chí phù hợp mục đích (fitness) cho C1–C12.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Mô tả mục tiêu sản phẩm, không chứng minh triển khai.
<a id="EV-003"></a>

### EV-003 · project.dependencies &amp; project.scripts

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/pyproject.toml · L5-L92
- **Phát hiện** · SDK agentsociety2 v2.12.0 khai báo 2 CLI scripts (agentsociety, agentsociety-workspace) và các phụ thuộc litellm, mcp\[cli\], mem0ai, faiss-cpu, ray (non-win32), duckdb, fastapi, pydantic, tiktoken.
- **Vai trò** · Đối chiếu dependency khai báo với mức sử dụng thực tế trong đường gọi.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Manifest chỉ phản ánh khai báo, không chứng minh runtime gọi tới.
<a id="EV-004"></a>

### EV-004 · locked package versions

- **Project và vị trí** · agentsociety2 · uv.lock · L1070-L3740
- **Phát hiện** · Khóa phiên bản: litellm==1.103.10 (L2034), mcp==2.3.0 (L2208), mem0ai==2.1.0 (L2273), ray==2.58.0 (L3739), faiss-cpu==1.15.1 (L1070), fastapi==0.141.1 (L1093), pydantic==2.13.5 (L3279).
- **Vai trò** · Định danh chính xác phiên bản dependency của snapshot.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Môi trường local chưa chạy uv sync nên chưa kiểm tra import trực tiếp các gói ngoài.
<a id="EV-005"></a>

### EV-005 · AgentBase.run\_react\_loop

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/agent/base/agent.py · L2038-L2345
- **Phát hiện** · Vòng lặp ReAct đa bước trong AgentBase: giữ thread append-only bảo toàn prompt-prefix cache, giới hạn \_max\_react\_turns (mặc định 10, whitelist 1..20), retry 1 lần trong lượt khi lỗi schema/parse, phản hồi lỗi qua role:tool hoặc &lt;schema\_error&gt;, tổng hợp fallback khi cạn lượt.
- **Vai trò** · Bằng chứng lõi cho phân loại Agent Harness, C1, C2, C8 và FLOW-01.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Chỉ xác minh qua đọc mã nguồn, chưa chạy LLM thật.
<a id="EV-006"></a>

### EV-006 · AgentBase.\_execute\_react\_tools &amp; dispatch\_react\_tool &amp; \_is\_core\_owned\_workspace\_path

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/agent/base/agent.py · L1393-L1956
- **Phát hiện** · Thực thi song song qua asyncio.gather cho đúng 5 action trong \_REACT\_PARALLEL\_SAFE\_ACTIONS ({'read','list','grep','read\_skill\_file','todo\_list'}, L1393-L1401, L1543-L1553), còn ask\_env(readonly=True) và memory\_\* chạy tuần tự; chặn write/append/ask\_env mutation khi readonly=True; bảo vệ tệp lõi bằng normpath+casefold (trả ReactToolResult(True, ...) no-op tại L1662-L1670); chuyển hướng skill env:\* sang ask\_env.
- **Vai trò** · Bằng chứng C4, C9 và FLOW-01.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Không thấy wall-clock timeout cấp vòng lặp run\_react\_loop.
<a id="EV-007"></a>

### EV-007 · PersonAgent.step, ask, build\_context\_refresh\_message, \_idle\_skip\_segment

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/agent/person.py · L354-L716
- **Phát hiện** · PersonAgent kế thừa AgentBase: chạy pre\_step hooks, hỗ trợ idle-skip fail-open cho giấc ngủ (mặc định tắt), gọi ask\_env('&lt;observe&gt;'), chạy run\_react\_loop, chạy post\_step hooks, gọi memory\_runtime.after\_step, và làm mới &lt;todo\_context&gt;/&lt;active\_skills&gt; giữa step mà không phá prefix cache.
- **Vai trò** · Bằng chứng C1, C2, C3 và FLOW-01.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phân tích tĩnh mã nguồn.
<a id="EV-008"></a>

### EV-008 · BASE\_RULES\_TEMPLATE, load\_prompt\_overrides, \_ask\_mode\_rules, json\_block

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/agent/person\_prompt.py · L14-L310
- **Phát hiện** · Thiết kế prompt tối ưu prefix-cache: khối base\_rules bất biến chia sẻ giữa mọi agent, json\_block dùng sort\_keys=True, hỗ trợ prompt\_overrides.json cấp run (fail-safe), và khối &lt;ask\_mode\_rules&gt; chứa chỉ thị OVERRIDE REJECTION chống prompt injection từ skill/env.
- **Vai trò** · Bằng chứng C2, C9 và FLOW-01.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Chống prompt injection dựa vào chỉ thị prompt, chưa có lớp lọc nội dung độc lập.
<a id="EV-009"></a>

### EV-009 · AgentSkillRuntime, ALLOWED\_ENV\_VARS, \_run\_in\_process

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/agent/base/skill\_runtime.py · L34-L950
- **Phát hiện** · Skill runtime chọn theo metadata (metadata-first): built-in chạy in-process nếu có entrypoint/hook; custom skill chạy trong subprocess cô lập qua skill\_worker.py với whitelist biến môi trường ALLOWED\_ENV\_VARS (chặn rò rỉ API key mặc định trừ khi khai báo AGENTSOCIETY\_SKILL\_ENV\_ALLOW) và timeout\_sec.
- **Vai trò** · Bằng chứng C4, C9 và FLOW-01.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Subprocess skill\_worker không đặt RLIMIT bộ nhớ hay cấm truy cập mạng/FS ngoài cwd.
<a id="EV-010"></a>

### EV-010 · \_invoke, main

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/agent/base/skill\_worker.py · L21-L137
- **Phát hiện** · Worker subprocess nạp động script skill qua importlib.util, chuyển hướng stdout của script sang stderr và trả JSON có cấu trúc về parent.
- **Vai trò** · Bằng chứng ranh giới thực thi custom skill (C4, C9).
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phân tích tĩnh.
<a id="EV-011"></a>

### EV-011 · PersonMemoryRuntime, MemoryRuntimeConfig

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/agent/memory\_runtime.py · L88-L250
- **Phát hiện** · PersonAgent quản lý bộ nhớ qua MEMORY.md + memory/episodes.jsonl (AgentMemoryStore), công cụ memory\_recent/memory\_search/memory\_range và hợp nhất định kỳ bằng LLM theo ngưỡng pending\_threshold/interval\_steps/importance; không dùng mem0ai.
- **Vai trò** · Bằng chứng C3, C7 và đối chiếu dependency mem0ai.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Chỉ đọc mã nguồn; kiểm tra fixture riêng ở EV-032.
<a id="EV-012"></a>

### EV-012 · AsyncMemory (mem0ai usage)

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/contrib/agent/llm\_donor\_agent.py · L8-L148
- **Phát hiện** · Tìm kiếm toàn bộ packages/agentsociety2/agentsociety2/ cho thấy mem0ai chỉ được import tại 1 contrib agent duy nhất (llm\_donor\_agent.py) và không lưu bền vào workspace; PersonAgent lõi không dùng mem0ai.
- **Vai trò** · Bằng chứng đối chiếu giữa dependency manifest và đường gọi thực tế (C3).
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phạm vi tìm kiếm giới hạn trong packages/agentsociety2/agentsociety2/.
<a id="EV-013"></a>

### EV-013 · \_step\_agent\_batch\_async, \_questionnaire\_agent\_batch\_async, step\_agent\_batch

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/agent/runner.py · L124-L350
- **Phát hiện** · Chạy tác tử theo lô dạng Ray Tasks không trạng thái (from\_workspace -&gt; step -&gt; to\_workspace -&gt; close), fan-out đồng thời bằng asyncio.gather, lưu best-effort khi lỗi giữa chừng, và đặt AGENTSOCIETY\_QUESTIONNAIRE\_TIMEOUT=600s cho từng agent trong questionnaire.
- **Vai trò** · Bằng chứng C6, C11 và FLOW-03.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Chưa chạy Ray cluster thực tế trong phiên kiểm toán.
<a id="EV-014"></a>

### EV-014 · RouterBase.init, step, from\_workspaces, to\_workspaces, acompletion\_with\_pydantic\_validation

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/env/router\_base.py · L179-L828
- **Phát hiện** · RouterBase tách 2 dispatcher (coder/default), dùng ContextVar \_trace\_ctx cho truy vết đồng thời, đặt timeout 900s cho env module step (hủy sibling khi lỗi), strict restore mặc định (ENV\_RESTORE\_ALLOW\_FRESH=False), và vòng lặp tự sửa JSON/Pydantic tới max\_llm\_call\_retry=10.
- **Vai trò** · Bằng chứng C1, C3, C8, C10, C11.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phân tích tĩnh.
<a id="EV-015"></a>

### EV-015 · CodeGenRouter, CodeStage.\_validate\_code\_safety, TemplateCacheDB, CacheCodeProvider

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/env/router\_codegen.py · L169-L2580
- **Phát hiện** · CodeGenRouter chạy pipeline 4 giai đoạn (Init-&gt;Code-&gt;Summary-&gt;ObserveFinal), kiểm tra AST chặt (cấm dunder/eval/exec/dangerous modules, chèn deadline guards), dừng ngay không retry nếu write\_attempted=True, và dùng FAISS IndexFlatIP + HMAC-SHA256 cache.pkl để tái sử dụng template code.
- **Vai trò** · Bằng chứng C1, C7, C8, C9 và FLOW-02.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Chưa thực thi codegen với LLM/FAISS thật.
<a id="EV-016"></a>

### EV-016 · Worker, WorkerPool, execute (and codegen\_worker.py:main)

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/env/codegen\_process.py · L39-L384
- **Phát hiện** · Process backend trên Linux chạy python -I -S codegen\_worker.py trong TemporaryDirectory, đặt PR\_SET\_PDEATHSIG, PR\_SET\_NO\_NEW\_PRIVS, RLIMIT\_AS (512 MiB), RLIMIT\_CORE=0, RLIMIT\_NOFILE=64, wall-clock timeout 10s và killpg(SIGKILL) khi lỗi; nhưng bị chặn trên non-Linux (Windows/macOS mặc định fallback inprocess).
- **Vai trò** · Bằng chứng C9, C11 và FLOW-02.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Kiểm toán trên Windows nên không thể chạy thực nghiệm Linux process worker.
<a id="EV-017"></a>

### EV-017 · ReActRouter.ask

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/env/router\_react.py · L104-L408
- **Phát hiện** · ReActRouter chạy vòng lặp tối đa max\_steps=10 với tool set\_status và phản hồi lỗi tool vào dialog; tuy nhiên chỉ truyền tools và tool\_choice='auto' ở step\_count==1, các bước sau truyền tools=None (L177-L185).
- **Vai trò** · Bằng chứng C1 và phát hiện hạn chế trên ReActRouter.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Cần kiểm chứng trên provider cụ thể xem việc bỏ tools ở lượt &gt;=2 có ngăn gọi tool đa bước hay không.
<a id="EV-018"></a>

### EV-018 · PlanExecuteRouter.ask, \_create\_plan, \_create\_replan

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/env/router\_plan\_execute.py · L74-L611
- **Phát hiện** · PlanExecuteRouter sinh kế hoạch JSON qua LLM coder, thực thi từng bước chặn tại max\_steps, và tự kích hoạt \_create\_replan (tối đa 3 lượt) khi gọi tool replan hoặc gặp lỗi tham số.
- **Vai trò** · Bằng chứng C5.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Thực thi tuần tự, không có DAG song song.
<a id="EV-019"></a>

### EV-019 · EnvRouterProxy.\_await\_actor\_call, create\_env\_router\_proxy

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/env/env\_router\_proxy.py · L33-L260
- **Phát hiện** · Bọc EnvRouterActor qua Ray: chỉ bật max\_concurrency=64 khi mọi env module is\_concurrency\_safe()==True (ngược lại=1); áp timeout theo thao tác (ask/step 900s, init/state 300s, close 60s) kèm ray.cancel; tuy nhiên set\_current\_time và set\_replay\_writer là fire-and-forget (L105-L121).
- **Vai trò** · Bằng chứng C6, C11 và FLOW-02/FLOW-03.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phân tích tĩnh.
<a id="EV-020"></a>

### EV-020 · AgentSociety.init, step, \_read\_checkpoint, from\_workspace

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/society/society.py · L608-L1046
- **Phát hiện** · AgentSociety điều phối mô phỏng không giữ object agent: ghi checkpoint 2 tệp (SOCIETY.json schema\_version=2 bất biến và SOCIETY\_STEP.json mỗi tick), đặt pending\_update='tick' trước step\_agent\_batch(max\_retries=0), xóa pending\_update sau env\_router.to\_workspaces(), và từ chối resume nếu phát hiện pending\_update!=None.
- **Vai trò** · Bằng chứng C3, C6, C11 và FLOW-03.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · AskStep/QuestionnaireStep không đặt pending\_update nên có thể chạy lại nếu crash trước mark\_step\_completed.
<a id="EV-021"></a>

### EV-021 · main, \_guard\_fresh\_run, ExperimentRunner

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/society/cli.py · L48-L1145
- **Phát hiện** · CLI entry agentsociety kiểm tra env sớm, chặn ghi đè run\_dir cũ khi chưa có --overwrite, hỗ trợ --resume khôi phục seed từ run\_manifest.json và bỏ qua các bước &lt; completed\_step\_count (tính remaining cho RunStep đang dở).
- **Vai trò** · Bằng chứng entry thực thi và FLOW-03.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Chưa chạy CLI thật vì thiếu .venv và LLM API key.
<a id="EV-022"></a>

### EV-022 · AgentSocietyHelper.\_run, \_replan, \_register\_tools

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/society/helper.py · L68-L1064
- **Phát hiện** · AgentSocietyHelper dùng Plan-and-Execute XML (max\_steps=8, max\_replans=2, 6 tools); nhưng trong \_run() (L180-L183, L224), sau khi \_replan() thay plan = new\_plan (theo prompt 'DO NOT repeat SUCCESS steps', L724), step\_index vẫn tính bằng len(execution\_history) — nếu len(new\_plan) &lt;= len(execution\_history) sẽ thoát sớm, còn nếu len(new\_plan) &gt; len(execution\_history) sẽ nhảy cóc phần đầu new\_plan. Tệp tests/test\_society\_helper\_xml.py (L1-L155) chưa có test nào cho \_run() hay \_replan().
- **Vai trò** · Bằng chứng C5 và phát hiện rủi ro/lỗi logic replan.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phát hiện qua truy vết tĩnh, chưa chạy test tái hiện vì thiếu litellm/elemental-xenon trong Python local.
<a id="EV-023"></a>

### EV-023 · PHASE\_VALIDATE\_COMMAND, prior\_phase\_gate\_issues (and cli.py, attestation.py, execution.py, review.py)

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/skills/analysis/harness/gates.py · L21-L163
- **Phát hiện** · Analysis Harness là deterministic CLI harness (0 lời gọi LLM trong 29 tệp) phục vụ AI agent bên ngoài (Claude Code/Codex): cưỡng chế thứ tự pha (frame-&gt;explore-&gt;claims-&gt;refine-&gt;produce-&gt;synthesis) bằng cổng 2 lớp (structural validator + LLM attestation), SHA-256 chống stale, file lock/receipt chống trùng lặp, và luồng experience memory 4 bước (draft-&gt;feedback-&gt;review-&gt;promote).
- **Vai trò** · Bằng chứng C3, C5, C8 và FLOW-04.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Không import trực tiếp được qua package root vì analysis/\_\_init\_\_.py kéo duckdb.
<a id="EV-024"></a>

### EV-024 · LLMClient, AdaptiveSemaphore, \_acquire\_shared\_quota, ThinkingSettings

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/config/llm\_dispatcher.py · L58-L1080
- **Phát hiện** · LLMClient tạo LiteLLM Router per-event-loop hỗ trợ openai/anthropic, timeout 60s, max\_retries=3 (fail-fast cho lỗi context limit, backoff mũ cho 429), điều tiết đồng thời AIMD (AdaptiveSemaphore), chuẩn hóa 5 format thinking/reasoning, và thống kê token (calls/input/output/cached\_input); nhưng không cấu hình fallback model chain, không tính chi phí USD, và \_acquire\_shared\_quota gọi import fcntl trực tiếp sẽ crash trên Windows nếu bật.
- **Vai trò** · Bằng chứng C10, C11, C12 và các phát hiện giới hạn đa nền tảng.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phân tích tĩnh.
<a id="EV-025"></a>

### EV-025 · ShardedAppendSink, JsonlTraceWriter

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/trace/sharded\_writer.py · L32-L395
- **Phát hiện** · Ghi trace OTel-compatible ra 256 shard JSONL với trace\_id/span\_id/parent\_span\_id (ContextVar), giới hạn 64 fd/sink và cắt giá trị dài; nhưng không fsync, không có file lock liên tiến trình trên Windows (fcntl=None), và nuốt OSError khi ghi.
- **Vai trò** · Bằng chứng C10, C11.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phân tích tĩnh.
<a id="EV-026"></a>

### EV-026 · ReplaySink, \_file\_lock, \_merge\_schema

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/storage/replay\_sink.py · L40-L267
- **Phát hiện** · ReplaySink ghi 256 shard JSONL dưới khóa file hỗ trợ cả POSIX fcntl và Windows msvcrt, ghi \_schema.json nguyên tử (fsync+replace, backup nếu corrupt); nhưng \_fds cache không có giới hạn eviction và dòng JSONL không fsync.
- **Vai trò** · Bằng chứng C3, C10, C11.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phân tích tĩnh.
<a id="EV-027"></a>

### EV-027 · call\_literature\_mcp\_tool, \_list\_literature\_tool\_names

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/skills/literature/mcp\_client.py · L15-L209
- **Phát hiện** · MCP client dùng Streamable HTTP (mcp SDK) với Bearer token tùy chọn và timeout 120s cho literature search; nhưng mỗi lần gọi mở 2 phiên HTTP/MCP riêng biệt liên tiếp (list\_tools rồi call\_tool), không có retry, và không nối vào vòng lặp simulation agent.
- **Vai trò** · Bằng chứng C4, C7.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Chưa gọi tới MCP server thực tế (https://llmapi.fiblab.net/mcp/).
<a id="EV-028"></a>

### EV-028 · BackendAuthMiddleware, BrowserOriginMiddleware, TrustedHostMiddleware

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/backend/app.py · L106-L300
- **Phát hiện** · FastAPI backend mặc định bind 127.0.0.1:8001, có TrustedHost, BrowserOrigin chống CSRF và BackendAuthMiddleware (loopback-only khi không đặt BACKEND\_TOKEN, hoặc 1 shared Bearer token dùng hmac.compare\_digest); nhưng không có RBAC và trả JSONResponse trên scope websocket khi từ chối (L199, L214).
- **Vai trò** · Bằng chứng C9.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phân tích tĩnh.
<a id="EV-029"></a>

### EV-029 · POST /scan, POST /test (CustomModuleScanner, SafeModuleTester)

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/backend/routers/custom.py · L121-L389
- **Phát hiện** · Endpoint scan/test/list custom module gọi importlib spec.loader.exec\_module() trực tiếp in-process trong FastAPI (backend/services/custom/scanner.py:L245, script\_generator.py:L102, và registry/modules.py:L51 qua custom.py:L160,L406 và modules.py:L46,L59); script\_generator.py:L183,L407 còn gọi cls(id=0, profile=...) mâu thuẫn với compatibility.py:L33,L230-L242 yêu cầu \_\_init\_\_() không tham số; backend/routers/agent\_skills.py cho phép upload/create script không quét tĩnh; kiểm tra toàn bộ backend/routers/ xác nhận 0 WebSocket routes.
- **Vai trò** · Bằng chứng C9 và phát hiện rủi ro bảo mật trọng yếu.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Chỉ áp dụng cho file trong workspace được cấu hình WORKSPACE\_PATH.
<a id="EV-030"></a>

### EV-030 · activate (BackendManager, AIChatInvoker, mcpServerManager)

- **Project và vị trí** · extension · extension/src/extension.ts · L24-L168
- **Phát hiện** · VS Code extension (ai-social-scientist v1.10.0) không tự chạy Agent Harness; đóng vai trò IDE workbench quản lý vòng đời FastAPI backend, kích hoạt AI coding agent bên ngoài (Claude Code/Codex/Cursor) và đồng bộ cấu hình MCP vào ~/.claude.json.
- **Vai trò** · Bằng chứng phân tách trách nhiệm hệ thống (C4, C6).
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Không kiểm tra mã nguồn của Claude Code / Codex CLI bên ngoài.
<a id="EV-031"></a>

### EV-031 · WorkspaceFS.write\_text, resolve (isolated fixture)

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/agent/base/workspace\_fs.py · L84-L152
- **Phát hiện** · Kiểm chứng fixture cô lập trên Python 3.13.15 (TemporaryDirectory): write\_text('notes.txt')=True, ghi '.runtime/secret.txt' bị chặn (runtime\_blocked=True), resolve('../outside.txt') ném ValueError (escape\_blocked=True).
- **Vai trò** · Bằng chứng thực thi mức fixture cho C9 (cách ly workspace).
- **Lớp xác minh** · Test có fixture
- **Trạng thái** · Quan sát thực thi
- **Tin cậy** · high
- **Giới hạn** · Chỉ xác minh module WorkspaceFS độc lập trên Windows, không thay thế kiểm thử E2E.
<a id="EV-032"></a>

### EV-032 · AgentMemoryStore.ensure, read\_memory\_md (isolated fixture)

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/agent/memory.py · L1-L120
- **Phát hiện** · Kiểm chứng fixture cô lập trên Python 3.13.15 (TemporaryDirectory): AgentMemoryStore.ensure() khởi tạo MEMORY.md hợp lệ (283 ký tự) trên đĩa.
- **Vai trò** · Bằng chứng thực thi mức fixture cho C3.
- **Lớp xác minh** · Test có fixture
- **Trạng thái** · Quan sát thực thi
- **Tin cậy** · high
- **Giới hạn** · Chỉ xác minh khởi tạo store cục bộ, chưa chạy LLM consolidation.
<a id="EV-033"></a>

### EV-033 · resolve\_workspace\_root, resolve\_under\_root (isolated fixture)

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/backend/path\_security.py · L27-L81
- **Phát hiện** · Kiểm chứng fixture cô lập trên Python 3.13.15: resolve\_workspace\_root khớp WORKSPACE\_PATH và resolve\_under\_root chặn '../etc/passwd' (traversal\_blocked=True).
- **Vai trò** · Bằng chứng thực thi mức fixture cho C9.
- **Lớp xác minh** · Test có fixture
- **Trạng thái** · Quan sát thực thi
- **Tin cậy** · high
- **Giới hạn** · Chưa kiểm tra FastAPI app end-to-end với HTTP/WebSocket.
<a id="EV-034"></a>

### EV-034 · 77 pytest modules in packages/agentsociety2/tests/ (+ 3 in examples/v2/daily\_mobility/tests/)

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/tests/test\_harness\_guardrails.py · L1-L50
- **Phát hiện** · Kho mã có sẵn 77 tệp kiểm thử pytest trong packages/agentsociety2/tests/ (46 gốc, 22 tests/framework/, 9 tests/skills/) cộng 3 tệp ở examples/v2/daily\_mobility/tests/, bao phủ ReAct loop, prompt cache, resume cursor, codegen isolation, shared quota, skill timeout, analysis harness guardrails và backend path security; chưa thể chạy cục bộ vì môi trường chưa cài uv/.venv/pytest/litellm/duckdb.
- **Vai trò** · Bằng chứng tồn tại Test Harness (C8) và giới hạn thực thi môi trường kiểm toán.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · medium
- **Giới hạn** · Chưa thực thi pytest trong phiên kiểm toán này.
<a id="EV-035"></a>

### EV-035 · TwoTierReActRouter.\_react\_with\_module (+ router\_two\_tier\_plan\_execute.py, router\_search\_tool.py)

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/env/router\_two\_tier\_react.py · L380-L391
- **Phát hiện** · TwoTierReActRouter lặp lại y hệt lỗi tools\_for\_call = tools\_with\_status if react\_steps == 1 else None (L380-L391) như ReActRouter; TwoTierPlanExecuteRouter không có vòng \_replan hay Pydantic validation; ngược lại SearchToolRouter (router\_search\_tool.py:L209-L238) truyền tools đầy đủ ở mọi bước.
- **Vai trò** · Bằng chứng bổ sung từ phản biện Vòng 2 (RV-001) cho Inventory, C1, C4, C5, F-006 và REC-04.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phân tích tĩnh mã nguồn.
<a id="EV-036"></a>

### EV-036 · \_load\_custom\_class (+ backend/routers/modules.py, backend/services/custom/compatibility.py)

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/registry/modules.py · L27-L52
- **Phát hiện** · registry/modules.py:\_load\_custom\_class() gọi spec.loader.exec\_module(module) trực tiếp in-process tại L51, được kích hoạt bởi POST /api/v1/custom/scan, GET /api/v1/custom/list, GET /api/v1/modules/agent\_classes và society/cli.py:L570.
- **Vai trò** · Bằng chứng bổ sung từ phản biện Vòng 2 (RV-002) cho C9, F-003 và REC-01.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phân tích tĩnh mã nguồn.
<a id="EV-037"></a>

### EV-037 · QuestionnaireRunner.run (+ skills/experiment/runner.py, skills/hypothesis/manager.py, extension/src/services/mcpClient.ts)

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/society/questionnaire.py · L243-L339
- **Phát hiện** · QuestionnaireRunner điều phối khảo sát song song nhiều agent (readonly=True, ép JSON 2 trường và retry riêng cho intention+choice); skills/experiment/runner.py &amp; skills/hypothesis/manager.py quản lý chuẩn bị thí nghiệm/PID; env/base.py chỉ dùng mcp Tool/ToolManager làm JSON Schema builder (EnvMeta.\_\_new\_\_ không kế thừa @tool từ concrete subclass); extension/src/services/mcpClient.ts:L100-L161 triển khai HTTP JSON-RPC + SSE probe MCP.
- **Vai trò** · Bằng chứng bổ sung từ phản biện Vòng 2 (RV-004) cho Inventory, C4, C6.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phân tích tĩnh mã nguồn.
<a id="EV-038"></a>

### EV-038 · RouterBase.\_llm\_completion\_span (+ env/benchmark.py)

- **Project và vị trí** · agentsociety2 · packages/agentsociety2/agentsociety2/env/router\_base.py · L265-L322
- **Phát hiện** · RouterBase.\_llm\_completion\_span chỉ gắn 4 thuộc tính (operation.type, llm.model, llm.source, input.message\_count ở L309-L314), thiếu toàn bộ llm.input\_tokens/cached\_input\_tokens/output\_tokens trên trace span phía env (dù society.py:L770-L830 có gom LLM\_STATS.json); env/benchmark.py dài 13 dòng chỉ là DTO Pydantic chưa có benchmark harness tự động.
- **Vai trò** · Bằng chứng bổ sung từ phản biện Vòng 2 (RV-005, RV-006) cho C10, F-007 và REC-05.
- **Lớp xác minh** · Mã nguồn tĩnh
- **Trạng thái** · Đối chiếu mã nguồn
- **Tin cậy** · high
- **Giới hạn** · Phân tích tĩnh mã nguồn.

## Phương pháp và phản biện

Điểm trưởng thành = tổng điểm các nhóm đủ căn cứ / (4 × số nhóm có điểm) × 100. Mức phù hợp = (số nhóm đáp ứng + 0,5 × số nhóm đáp ứng một phần) / số nhóm đã đối chiếu được kết quả yêu cầu × 100. Mẫu rỗng cho kết quả N/A. Hai tỷ lệ được diễn giải theo các mẫu số riêng.

- **Trạng thái** · Đã phản biện
- **Phạm vi** · Reviewer độc lập ở ngữ cảnh mới đã đối chiếu git snapshot, mã băm 2 tệp vòng một, tự lần trực tiếp mã nguồn trên society/helper.py, env/router\_react.py, env/router\_two\_tier\_react.py, env/router\_search\_tool.py, backend/services/custom/\*, registry/modules.py, agent/person.py, agent/base/agent.py, society/society.py, env/router\_base.py, trace/sharded\_writer.py và rà soát toàn bộ 12 nhóm C1–C12 (phân biệt rõ kiểm chứng tĩnh và giới hạn chưa chạy runtime).
- **Người hoặc tác tử phản biện** · Subagent Reviewer Độc lập (conv:61f59359-9c42-404c-b4a5-419c53c97257)
- **Model** · pro (khai báo qua invoke\_subagent; host không lộ tên model chính xác để xác minh độc lập)
- **Kết luận** · Chấp nhận có điều chỉnh (Accept with revisions) — toàn bộ 7 điểm phản biện đã được tiếp thu vào bản cuối.
- **Snapshot** · d:/PROJECTS/AgentSociety @ main (e7186aad430e, working tree clean)
- **SHA-256** · Agent\_Harness\_Audit.md · 99fd0d57dbb14e6b03134edbef244d800de09773bbac58df0b888fc493f610be
- **SHA-256** · Agent\_Harness\_Evidence.json · 11fe6129eef3ac9a4eea10a6cc0f0d9e7f123bf1a98c3f30c5aaddff9f68cac0

### RV-001 · high · Đã tiếp thu

- **Ý kiến** · Vòng 1 bỏ sót 3 env routers (TwoTierReActRouter, TwoTierPlanExecuteRouter, SearchToolRouter) và bỏ sót lỗi anh em tools=None từ bước 2 trong TwoTierReActRouter.
- **Đối chứng** · env/router\_two\_tier\_react.py:L380-L391 lặp lại y hệt tools\_for\_call = tools\_with\_status if react\_steps == 1 else None; env/router\_search\_tool.py:L209-L238 truyền tools ở mọi bước.
- **Xử lý** · Đã bổ sung EV-035, cập nhật đủ 6 routers vào Inventory/Architecture và mở rộng F-006, REC-04, C1, C4 sang TwoTierReActRouter. [EV-017](#EV-017) [EV-035](#EV-035)

### RV-002 · high · Đã tiếp thu

- **Ý kiến** · F-003 trích nhầm dòng exec\_module ở scanner.py, bỏ sót đường exec\_module thứ 2 ở registry/modules.py:L51, bỏ sót lỗi contract script\_generator.py và phóng đại bề mặt WebSocket (0 WS routes).
- **Đối chứng** · scanner.py:L245 mới là exec\_module; registry/modules.py:L51 chạy exec\_module cho custom/scan, custom/list, modules/agent\_classes, cli.py; script\_generator.py:L183,L407 gọi cls(id=0, profile=...) trái compatibility.py:L33; 0 WS routes trong backend/routers/.
- **Xử lý** · Đã sửa EV-029, thêm EV-036, mở rộng F-003 và REC-01 sang registry/modules.py và script\_generator.py, đồng thời hạ hạng mục WebSocket auth xuống vệ sinh phòng thủ. [EV-028](#EV-028) [EV-029](#EV-029) [EV-036](#EV-036)

### RV-003 · medium · Đã tiếp thu

- **Ý kiến** · F-004 mới nêu nhánh thoát sớm khi len(new\_plan) &lt;= len(execution\_history), chưa nêu nhánh nhảy cóc phần đầu new\_plan khi len(new\_plan) &gt; len(execution\_history) và thiếu bằng chứng chưa có test \_run()/\_replan().
- **Đối chứng** · society/helper.py:L180-L183, L224, L724; tests/test\_society\_helper\_xml.py:L1-L155 chỉ có 6 test parse/dispatch, không có test \_run()/\_replan().
- **Xử lý** · Đã bổ sung đầy đủ cả 2 chiều lỗi con trỏ replan và khoảng trống test vào EV-022 và F-004. [EV-022](#EV-022)

### RV-004 · medium · Đã tiếp thu

- **Ý kiến** · Bỏ sót QuestionnaireRunner, skills/experiment/, skills/hypothesis/ và extension/src/services/mcpClient.ts; cần làm rõ EnvBase chỉ dùng mcp SDK làm schema builder.
- **Đối chứng** · society/questionnaire.py:L243-L339, skills/experiment/runner.py, skills/hypothesis/manager.py, env/base.py:L53-L54,L343, extension/src/services/mcpClient.ts:L100-L161.
- **Xử lý** · Đã thêm EV-037, cập nhật Inventory (Components &amp; Frameworks.mcp) và mô tả C4/C6. [EV-037](#EV-037)

### RV-005 · medium · Đã tiếp thu

- **Ý kiến** · EV-034 đếm thiếu tệp test (46 thay vì 77+3) và F-007 bỏ sót khoảng trống thiếu 100% trường token ở RouterBase.\_llm\_completion\_span cùng drop OSError ở ShardedAppendSink.
- **Đối chứng** · packages/agentsociety2/tests/ có 77 tệp (46 gốc + 22 framework/ + 9 skills/) + 3 tệp daily\_mobility; env/router\_base.py:L265-L322 chỉ ghi 4 thuộc tính span không có token.
- **Xử lý** · Đã cập nhật EV-034 thành 77 (+3) tệp pytest, thêm EV-038 và mở rộng F-007, REC-05, C10. [EV-034](#EV-034) [EV-038](#EV-038)

### RV-006 · medium · Đã tiếp thu

- **Ý kiến** · C1.fitness=met và C8.fitness=met quá cao so với lỗi đa router và 0/77 pytest chạy thực tế; C4 không nên trừ điểm vì MCP không nối agent loop (trái audit-method.md:L35); C10 nên cân nhắc 2/4.
- **Đối chứng** · audit-method.md:L35, L44; lỗi ReActRouter/TwoTierReActRouter; 0/77 pytest chạy cục bộ; thiếu token ở RouterBase span và benchmark runner.
- **Xử lý** · Đã hạ C1.fitness và C8.fitness xuống partial, sửa lập luận C4 sang khuyết tật kỹ thuật thực tế, hạ C10.score xuống 2/4 và tính lại toàn bộ scores (overall=66.67, fitness\_pct=66.67). [EV-034](#EV-034) [EV-035](#EV-035) [EV-037](#EV-037) [EV-038](#EV-038)

### RV-007 · low · Đã tiếp thu

- **Ý kiến** · FLOW-01 cần nêu chính xác 5 action trong \_REACT\_PARALLEL\_SAFE\_ACTIONS và hành vi trả ok=True no-op cho core-owned path; F-006 cần tách lỗi bug khỏi đánh đổi thiết kế của LLMClient.
- **Đối chứng** · agent/base/agent.py:L1393-L1401, L1543-L1553, L1662-L1670; config/llm\_dispatcher.py:L422-L457.
- **Xử lý** · Đã cập nhật chính xác chi tiết kỹ thuật trong EV-006, FLOW-01 và F-006. [EV-006](#EV-006) [EV-024](#EV-024)
Toàn bộ 7 mục phản biện (2 high, 4 medium, 1 low) đã được tiếp thu, cập nhật vào sổ bằng chứng và tính lại chỉ số; không còn mục mở.
