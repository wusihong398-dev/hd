# 硬盘健康卫士 Windows 构建仓库

本仓库使用 GitHub Actions 在 Windows x64 runner 上构建独立单文件 EXE。

## 首次准备
1. 下载本项目对应的完整源码包：`硬盘健康卫士_v0.3.1_第四次构建修复包.zip`。
2. 将 ZIP 上传到本仓库根目录，文件名必须为 `source_bundle.zip`。
3. 提交后会自动触发 `Windows EXE 构建` 工作流；也可在 Actions 页面手动运行。

## 构建流程
- Windows Server runner + Python 3.11 x64。
- 从 smartmontools 官方 GitHub Release 下载 7.5 安装包。
- 对安装包执行 SHA256 校验。
- 使用 7-Zip 提取 smartctl.exe 与 drivedb.h，不安装到系统。
- 执行 Python 语法检查及核心单元测试。
- PyInstaller 构建 `硬盘健康卫士.exe` 单文件。
- 上传 `硬盘健康卫士-Windows-x64` 构建产物。

## 下载 EXE
打开 GitHub 仓库的 Actions，进入最新成功的 `Windows EXE 构建` 运行记录，在 Artifacts 中下载 `硬盘健康卫士-Windows-x64`。

注意：EXE 尚未构建。必须先上传 `source_bundle.zip`；工作流不会在源码缺失时伪报成功，也不会跳过 SMART 组件 SHA256 校验。
