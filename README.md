# TO PDF · 中文批注 — Web 版

桌面版 [TO PDF](../TO%20PDF) 的 Web 迁移，保留相同 UI 与批注工作流，可部署到 Vercel。

## 功能

- PDF / PPT 导入（PPT 服务端转换为 PDF）
- 实时 PDF 预览（pdf.js）
- 批注管理：原位译文、标记、术语、重点、补充说明
- 手绘墨迹（笔 / 荧光笔 / 橡皮）
- AI 单页 / 批量批注（DeepSeek、OpenAI、小米 MiMo、Agnes 等）
- 导出带批注 PDF
- 工程保存 / 打开（`.topdf` JSON）
- 放映模式（演示工具）

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | 原版 Electron HTML/CSS/JS + pdf.js |
| 状态 | IndexedDB（文件）+ localStorage（会话/设置） |
| 后端 | Python 无状态 API（PyMuPDF、python-pptx、CrewAI） |
| 部署 | Vercel 静态站点 + Python Serverless |

## 本地开发

### 1. 安装 Python 依赖

```bash
cd "E:\desktop\To PDF Web"
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements-full.txt
```

### 2. 启动开发服务器

```bash
npm run dev
# 或: python scripts/local_dev.py
```

浏览器打开 http://127.0.0.1:3000

### 3. 配置 API Key

在应用内「系统 API 设置」填写，或在环境变量中设置（推荐生产环境）：

```
TOPDF_DEEPSEEK_API_KEY=sk-...
TOPDF_OPENAI_API_KEY=sk-...
TOPDF_XIAOMI_API_KEY=...
TOPDF_AGNES_API_KEY=...
```

## 部署到 Vercel（GitHub → Vercel）

### 1. 推送到 GitHub

```bash
cd "E:\desktop\To PDF Web"
git init
git add .
git commit -m "Initial web version of TO PDF annotator"
git remote add origin https://github.com/YOUR_USER/topdf-web.git
git push -u origin main
```

### 2. 在 Vercel 导入项目

1. 登录 [vercel.com](https://vercel.com) → **Add New Project**
2. 选择 GitHub 仓库 `topdf-web`
3. Framework Preset: **Other**
4. Root Directory: `.`（默认）
5. **Build Command / Output Directory 均留空**（不要填 `public`，否则 `api/` 函数会失效）
6. 在 **Environment Variables** 添加 LLM API Key（见上文）
6. 点击 **Deploy**

### 3. 部署后验证

- 访问 `https://your-app.vercel.app` — 主界面
- 访问 `https://your-app.vercel.app/api/health` — 应返回 `{"ok":true,"backend":"web","api_version":2}`
- 导入 PDF → 预览 → 手动添加批注 → 导出

### Vercel 注意事项

- **函数超时**：Hobby 计划约 10s，Pro 可配置 60s（`vercel.json` 已设 `maxDuration: 60`）。批量批注在 Web 版改为**前端逐页调用**，避免单次超时。
- **依赖体积**：Vercel 使用精简版 `requirements.txt`（不含 CrewAI），避免超过 500MB 限制；单模型批注/原位译文可用。本地完整功能请 `pip install -r requirements-full.txt`。
- **冷启动**：PyMuPDF 较大，首次调用可能较慢。
- **Ollama**：本地 Ollama 在纯 Web 部署中不可用（无 localhost 访问）。

## 项目结构

```
To PDF Web/
├── api/                 # Vercel Python Serverless
│   ├── index.py         # /api/* 入口
│   └── web_handlers.py  # 无状态业务逻辑
├── public/              # 静态前端（原版 Electron UI）
│   ├── index.html
│   ├── styles/
│   ├── components/
│   ├── services/
│   ├── preview/         # 放映模式
│   └── vendor/pdfjs/
├── src/                 # Python 业务代码（自桌面版复制）
├── config/default.yaml
├── scripts/local_dev.py
├── vercel.json
├── requirements.txt
└── package.json
```

## 与桌面版差异

| 功能 | 桌面版 | Web 版 |
|------|--------|--------|
| 文件导入 | 本地路径 / 拖拽 | 浏览器文件选择器 |
| 会话持久化 | 磁盘 auto-save | IndexedDB + localStorage |
| 批量批注进度 | 后端线程 + 轮询 | 前端逐页调用 API |
| Ollama 本地模型 | ✅ | ❌ |
| 工程文件 | 含 PDF 副本的 .topdf zip | JSON 元数据（PDF 在 IndexedDB） |
| 放映模式 | 独立 Electron 窗口 | 新标签页 + localStorage 桥接 |

## 许可证

MIT License
