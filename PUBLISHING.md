# Publishing TokenStep for Windows

This is the community **Windows port** of [TokenStep](https://github.com/Backtthefuture/TokenStep)
(macOS, MIT © 2026 AI产品黄叔 / Chaoqiang Huang). Plan: publish as a **standalone repo** with full
attribution, ship the portable `.zip` on GitHub Releases, and open a friendly issue
on the original repo offering to upstream / be linked.

> Repo: **`jsun2020/TokenStep-Windows`**. `LICENSE`, `README.md`, and
> `tokenstep/updater.py` are already wired to this owner.

## 1. Create the repo (web UI — no `gh` needed)

1. On github.com → **New repository** → name `TokenStep-Windows`, Public, **do not**
   add a README/.gitignore/license (we already have them).
2. Push the existing local repo:

   ```sh
   cd C:/Users/sr9rfx/.claude-project/TokenStep/TokenStepWin
   git remote add origin https://github.com/jsun2020/TokenStep-Windows.git
   git branch -M main
   git push -u origin main
   ```

   > Behind the corporate proxy, if push hangs/fails: set
   > `git config --global http.proxy http://<proxy-host>:<port>` (or use GitHub Desktop).
   > `dist/` and `build/` are gitignored, so the binary is **not** pushed — it goes to Releases.

## 2. Publish the portable build as a Release

GitHub web UI → **Releases → Draft a new release**:

- Tag: `v0.1.7`  (Target: `main`)
- Title: `TokenStep for Windows 0.1.7`
- Description: paste the **Release notes** below
- **Attach binary:** upload `dist/TokenStep-0.1.7-win64.zip`
- Publish.

The in-app updater (`检查更新`) will look at `https://api.github.com/repos/jsun2020/TokenStep-Windows/releases/latest`
and detect the Windows `.zip` asset, so future releases auto-notify users.

### Release notes (paste into the release)

```
TokenStep for Windows — a community Windows port of TokenStep (macOS) by AI产品黄叔 (Chaoqiang Huang).
Tracks your AI token usage like a daily step ring, in the system tray. Local-only.

Download: TokenStep-0.1.7-win64.zip — unzip and run TokenStep.exe (no install, no Python needed).

Synced with macOS through v0.1.7:
- System-tray step-ring icon + today's goal progress
- HTML dashboard at parity with the macOS "今日" view
- Incremental collector cache (fast refresh over large logs)
- OpenAI per-part pricing for Codex gpt-5.5 / gpt-5.4
- v0.1.5 brand icon
- Share-card screenshot: copy / save a "今日" stats card to share to the community

Note: the .exe is unsigned, so SmartScreen may warn on first run — click "More info → Run anyway".
Credit & thanks to the original macOS app: https://github.com/Backtthefuture/TokenStep (MIT).
```

## 3. Courtesy issue on the original repo (recommended)

Open an issue at https://github.com/Backtthefuture/TokenStep/issues with this draft:

```
标题：[社区] TokenStep 的 Windows 版本（系统托盘端口）

你好黄叔，先感谢你做的 TokenStep，「每天一个亿」的理念太有意思了 🙌

我基于它做了一个 Windows 版本（系统托盘应用，Python + pystray + Pillow 实现），
复用了你 collector 的读取逻辑，并尽量对齐了 UI/图标/分享卡片等体验，已同步到 v0.1.7
（含自动分享截图）。遵循 MIT 协议，完整保留了你的版权与署名。

仓库：https://github.com/jsun2020/TokenStep-Windows
（便携版可直接在 Releases 下载，解压即用，无需安装。）

想问下：
1) 你是否愿意在 README 里加一个「Windows 版本（社区维护）」的链接？
2) 或者你更希望以某种形式合并到主仓库？由于是另一套技术栈（Python，而非 Swift），
   我觉得独立仓库 + 链接可能对你维护负担最小，但完全尊重你的想法。

无论如何都谢谢你的开源，按你方便的方式来就好 🙏

---
EN: A community Windows port of TokenStep (tray app, Python). MIT, attribution kept.
Repo + portable download: https://github.com/jsun2020/TokenStep-Windows
Happy to be linked from your README, or to discuss upstreaming — your call. Thanks!
```
