# FinSage API 服务镜像（T1107）
# 构建上下文 = 项目根 `docker compose --profile app build`
# 参考资料：m11 T1107；入口对应 src/finsage/api/app.py 的 factory。
# 注意：镜像内仅安装应用与运行依赖；模型资源不烧录入镜像（运行时按只读+在线兜底策略加载）。
FROM python:3.11-slim

# 非交互 + 无 pyc，减小镜像体积
# 注意：不用 PIP_NO_CACHE_DIR，改为 BuildKit cache mount 复用 pip 下载缓存（跨构建加速）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 容器内 pip 走国内镜像，避免访问官方源超时（与宿主机 .pip/pip.ini 同源，见 .env.example 注释）
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_EXTRA_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app

# 先复制元数据与源码，再安装当前包（含 ./src 的 finsage 包）
COPY pyproject.toml alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY scripts ./scripts

# 以 editable 方式安装，使 finsage.api.app 可直接被 uvicorn 加载。
# --mount=type=cache,target=/root/.cache/pip：复用 pip 下载缓存，同一台机器多次构建不重复下载依赖。
# 安装 retrieval extra：BGE-M3 嵌入依赖（FlagEmbedding + torch 系）拆为可选 extra，
# 基础镜像默认不拉取；启用容器内 RAG（/research 检索）时必须带上，否则嵌入模型无法加载、
# 检索抛 FIN-3001。模型权重经运行时只读卷挂载（resources/models），此处仅装 Python 依赖。
#
# 关键：本容器为 CPU-only（python:3.11-slim，无 GPU）。torch>=1.6.0 在 PyPI 默认解析为
# CUDA 构建，会把 nvidia-cublas/cudnn/cusolver 等数 GB 的 cu13 包一并拉入，既拖慢构建又撑大
# 镜像。故先以 pytorch CPU 专用索引预装 CPU-only torch（约 190MB），后续 editable 安装解析到
# torch 已满足 >=1.6.0 即跳过整套 CUDA 依赖。
RUN --mount=type=cache,target=/root/.cache/pip pip install --index-url https://download.pytorch.org/whl/cpu torch
RUN --mount=type=cache,target=/root/.cache/pip pip install --editable ".[retrieval]"

# Web 服务默认端口（外部映射见 docker-compose.yml，容器内固定 8000）
EXPOSE 8000

# 应用入口：FastAPI factory 模式
# 配置文件由 docker-compose env_file 注入；容器启动后才产生，故运行期不加 --reload
CMD ["uvicorn", "finsage.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]