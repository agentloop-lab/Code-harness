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
- 可显式启用的可复用 Skills
- 文件修改后的验证感知完成约束
- 重复工具调用的无进展提醒和提前终止
- 紧凑的工具输出、文件状态和代码差异展示

## 项目架构

![Code Harness 运行架构](Model.png)

用户任务首先进入 CLI。CLI 负责会话、项目记忆、Skills、文件引用和
Plan/Act Mode 等交互功能；Context Manager 为模型整理长度可控的上下文；
Agent Loop 根据模型的判断发起工具调用；Tool Executor 则负责工作区隔离，
并在 Plan Mode 下限制写入和命令执行。

## 核心运行机制

- **上下文管理：** 过长的工具结果会完整保存到本地，上下文中只留下预览；
  每次请求模型前会精简较旧的工具输出，如果仍然超过预算，再把早期对话整理成
  摘要，同时保留当前任务。
- **Safe Edit：** 读取文件时记录版本。如果编辑前文件已经发生变化，系统会拒绝
  基于旧版本的修改，要求 Agent 重新读取后再继续。
- **验证与无进展保护：** 文件改动后，Agent 必须运行合适的验证命令，或者明确
  说明为什么无法验证。连续重复完全相同的工具调用时，系统会先提醒，再停止任务。

## 安装

Code Harness 需要 Python 3.10 或更高版本。

```bash
python -m pip install -e .
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
code-harness
```

直接执行单次任务：

```bash
code-harness "创建一个 Hello World 脚本"
```

指定其他工作区：

```bash
code-harness --workspace path/to/project
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
| `/skills` | 查看可用的 Skills |
| `/skill <名称\|off>` | 启用一个 Skill 或关闭当前 Skill |
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

## Skills

Skill 是一个为特定任务提供可复用说明的 `SKILL.md` 文件。随项目提交的 Skill
放在 `skills/`，不希望提交到仓库的本地 Skill 可以放在 `.agent/skills/`。
只有用户明确选择的 Skill 才会加入 Agent 指令，并且不能绕过工作区或工具限制。

```text
skills/
└── python-testing/
    └── SKILL.md
```

```text
Task> /skills
Task> /skill python-testing
Task> 检查并修复当前失败的 Python 测试
Task> /skill off
```

选择结果只在本次 CLI 进程中生效。

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
