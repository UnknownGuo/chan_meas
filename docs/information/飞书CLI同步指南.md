- feishu-cli 需要你的飞书权限才能读写云文档。 - 方式有两种（任选其一）： - **推荐方式**（最简单）：在终端运行 `feishu-cli auth login`，它会自动打开浏览器让你扫码/登陆飞书账号，授权后自动保存 token。
首先要claude code帮我安装feishu cli

### 2. 如何把整个项目目录（含很多子文件夹 + .md 文件）导入飞书？要保持和项目一模一样的分级逻辑，能任意查看任意 .md 文件
**核心结论**：  
Obsidian 本地目录**完全不用改**，仍然和你项目一模一样（子文件夹层级完全保留）。  
飞书CLI 是**把本地 .md 文件上传/转换**成飞书云文档，不是把整个文件夹“镜像”成飞书文件系统。

**具体操作步骤**（Linux 终端里做）： 1. 先安装 feishu-cli（一次就好）： ```bash curl -fsSL  https://raw.githubusercontent.com/riba2534/feishu-cli/main/install.sh  | bash ``` 2. 登陆（见上面第1点）。

3. **导入单个 .md 文件**（最常用）：
   ```bash
   feishu-cli doc import /你的项目路径/子文件夹A/笔记
                  1.md
                   --title "笔记1标题" --upload-images
   ```
   - `--upload-images` 会自动上传图片。
   - 第一次导入会创建新云文档，CLI 会返回一个飞书文档链接。

4. **批量导入整个项目（含所有子文件夹）**：
   feishu-cli 没有“一键导入整个文件夹结构”的内置命令，但可以用一行简单命令循环处理（推荐让 Claude 帮你生成脚本）：
   ```bash
   # 示例：遍历项目里所有 .md 文件并导入
   find /你的项目根目录 -type f -name "*.md" -print0 | xargs -0 -I {} feishu-cli doc import "{}" --title "$(basename "{}" .md)" --verbose
   ```

更新命令示例（推荐）： ```bash # 用本地最新 .md 覆盖已有的飞书文档（需要知道文档的 doc_token） feishu-cli doc batch-update DOC_TOKEN_HERE --markdown /你的项目/子文件夹/更新后的笔记.md ``` 或者更简单： ```bash feishu-cli doc import /你的项目/更新后的笔记.md --doc-token 已有的文档token ``` **实用建议**： - 第一次导入后，记下每个文档的 `doc_token`（CLI 会显示）。 - 你可以用 Claude 在终端里写一个简单脚本：检测哪些 .md 文件改动过，然后自动运行 import 命令覆盖。 - 这样就实现了“本地改完 → 运行一条命令 → 飞书自动更新”。 ### 总结对比（帮你快速决策） - **优点**：不用额外同步文件夹，不用 Syncthing，不用 Git；直接把本地 .md 推到飞书云文档，协作很方便；支持图片、图表等。 - **缺点**：不是实时自动双向同步（需要手动/脚本触发）；飞书侧是云文档，不是原始文件夹结构（但 Obsidian 本地结构完全不变）。 - **适合你**：如果你主要在本地用 Obsidian + Claude 写，偶尔需要把内容分享/同步到飞书给别人看，这套方案非常轻量。
