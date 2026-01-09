# Flet Windows 打包脚本
#
# 用法（在仓库根目录执行）：
#   powershell -ExecutionPolicy Bypass -File .\\flet_gui\\build_windows.ps1
#
# 说明：
# - 该脚本会调用 `flet build windows` 生成桌面应用
# - 输出目录默认：dist/flet-gui/

$ErrorActionPreference = "Stop"

$py = "python"

Write-Host "Installing/Upgrading flet ..."
& $py -m pip install -U flet
if ($LASTEXITCODE -ne 0) { throw "Failed to install flet" }

Write-Host "Building Windows app ..."
& flet build windows -o "dist/flet-gui" "flet_gui" --product "OAI Team Auto Provisioner" --description "OAI Team Auto Provisioner (Flet GUI)" --yes
if ($LASTEXITCODE -ne 0) { throw "flet build failed" }

Write-Host "Done. Output: dist/flet-gui"

