# 把本发布仓库同步到 DSH 运行位置（vendor 目录），供 web profile 使用。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File sync_to_vendor.ps1
#   powershell -ExecutionPolicy Bypass -File sync_to_vendor.ps1 -Vendor "D:\somewhere\dsh-origin-thesis"
#
# 为什么需要这一步：profile 的 node_modules 里是指向 vendor 目录的 junction，
# 而 DSH 启动 MCP 服务器时用的是 vendor 目录里的文件。改完源码同步一次，
# 重启 Harness（或等热加载）后生效。

param(
    [string]$Vendor = (Join-Path $env:USERPROFILE 'dsh-vendor\dsh-origin-thesis')
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# 只同步运行期需要的文件；源码仓库里的 README/LICENSE 同步过去也无害。
$files = @(
    'thesis_mcp_server.py',
    'styles.json',
    'cordis.patch.yml',
    'index.js',
    'package.json',
    'format_thesis_figures.py',
    'format_composite.py',
    'export_figures.py',
    'README-thesis.md',
    'LICENSE',
    'THIRD-PARTY-NOTICES.md'
)

if (-not (Test-Path $Vendor)) {
    New-Item -ItemType Directory -Force -Path $Vendor | Out-Null
    Write-Host "created $Vendor"
}

foreach ($f in $files) {
    $src = Join-Path $here $f
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $Vendor $f) -Force
        Write-Host "  synced $f"
    } else {
        Write-Host "  skip   $f (not present in repo)"
    }
}

# 清理运行期缓存，避免旧字节码干扰
$pyc = Join-Path $Vendor '__pycache__'
if (Test-Path $pyc) { Remove-Item $pyc -Recurse -Force; Write-Host "  cleaned __pycache__" }

Write-Host ""
Write-Host "synced -> $Vendor"
Write-Host "verify with: python thesis_mcp_server.py --info"
