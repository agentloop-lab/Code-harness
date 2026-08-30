# Code Harness

简体中文 | [English](README.md)

一个面向自主软件工程任务的轻量级 Coding Agent Harness。

## 已实现功能

- 兼容 OpenAI API 格式的模型客户端
- 支持文件读写、文本搜索、文件编辑和命令执行的 Agent Loop
- 工作区隔离和安全文件编辑
- 多轮对话与会话持久化
- 手动和自动上下文压缩
- 项目记忆与 `@文件` 引用
- 执行前可审查的只读 Plan Mode
- 紧凑的工具输出、文件状态和代码差异展示

## 安装

Code Harness 需要 Python 3.10 或更高版本。

```bash
python -m pip install -r requirements.txt
```

将 `.env.example` 复制为 `.env`，然后填写 API 配置：

```dotenv
OPENAI_API_KEY=
OPENAI_BASE_URL=
MODEL_NAME=
```

如果模型服务使用 SDK 的默认地址，可以不填写 `OPENAI_BASE_URL`。

## 使用方法

启动交互式 CLI：

```bash
python -B main.py
```

直接执行单次任务：

```bash
python -B main.py "创建一个 Hello World 脚本"
```

指定其他工作区：

```bash
python -B main.py --workspace path/to/project
```

在 CLI 中输入 `/` 可以查看和补全命令：

| 命令 | 作用 |
| --- | --- |
| `/open <path>` | 切换到一个已有工作区 |
| `/workspace` | 显示当前工作区 |
| `/resume` | 恢复已保存的会话 |
| `/plan <task>` | 使用只读工具探索项目并生成计划 |
| `/act` | 执行经过审查的最新计划 |
| `/cancel` | 放弃当前计划 |
| `/compact` | 压缩当前会话上下文 |
| `/remember <note>` | 保存一条项目记忆 |
| `/memory` | 查看项目记忆 |
| `/status` | 查看最近一次任务修改的文件 |
| `/diff` | 查看最近一次任务产生的文本差异 |
| `/verbose` | 切换完整工具输出 |
| `/help` | 显示命令帮助 |
| `/exit` | 保存会话并退出 |

在任务中使用 `@` 引用工作区文件：

```text
Task> 检查 @src/main.py 并改进错误处理
```

Plan Mode 支持在执行前反复调整计划：

```text
Task> /plan 增加输入参数校验
Plan> 不要增加新的依赖
Plan> /act
```

## 测试

运行完整测试，并避免生成字节码缓存：

```bash
python -B -m unittest discover -s tests
```

真实 API 测试默认关闭。确认 `.env` 中的 API 配置可用后，可以在 PowerShell 中运行：

```powershell
$env:RUN_LIVE_TESTS = "1"
python -B -m unittest tests.test_live_agent -v
```

## 状态

正在积极开发中。
