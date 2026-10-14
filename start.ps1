# ==================================================
#  Deep Agent Search  -  一键启动 (PowerShell)
#  用法（在项目根目录）:  powershell -ExecutionPolicy Bypass -File .\start.ps1
# ==================================================
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Deep Agent Search  -  一键启动 (Docker)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# ---------- 环境文件自举（.env 与 docker/.env.docker）----------
# 新机器 clone 后这两个文件并不存在（已从 git 移除、仅保留 .example 模板）。
# 这里负责从模板生成，并保证两处 MYSQL_PASSWORD 一致。
$envFile          = Join-Path $PSScriptRoot '.env'
$envExample       = Join-Path $PSScriptRoot '.env.example'
$dockerEnvFile    = Join-Path $PSScriptRoot 'docker\.env.docker'
$dockerEnvExample = Join-Path $PSScriptRoot 'docker\.env.docker.example'

# docker/.env.docker 会被挂载为容器内 /app/.env；若该路径上存在目录而非文件，
# Docker 会以同名目录挂载，导致容器行为异常。此处提前拦截。
if ((Test-Path -LiteralPath $dockerEnvFile) -and -not (Test-Path -LiteralPath $dockerEnvFile -PathType Leaf)) {
    Write-Host "[错误] $dockerEnvFile 已存在但不是文件（很可能是 Docker 误建的目录）。" -ForegroundColor Red
    Write-Host "       请先删除该目录后重试：Remove-Item -Recurse -Force '$dockerEnvFile'"
    exit 1
}

$genEnv = $false
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    if (Test-Path -LiteralPath $envExample -PathType Leaf) {
        Copy-Item -LiteralPath $envExample -Destination $envFile -Force
        $genEnv = $true
        Write-Host "[自举] 已从 .env.example 生成 .env" -ForegroundColor Cyan
    } else {
        Write-Host "[警告] 未找到 .env.example，无法自动生成 .env，请手动创建。" -ForegroundColor Yellow
    }
}

$genDockerEnv = $false
if (-not (Test-Path -LiteralPath $dockerEnvFile -PathType Leaf)) {
    if (Test-Path -LiteralPath $dockerEnvExample -PathType Leaf) {
        Copy-Item -LiteralPath $dockerEnvExample -Destination $dockerEnvFile -Force
        $genDockerEnv = $true
        Write-Host "[自举] 已从 docker/.env.docker.example 生成 docker/.env.docker" -ForegroundColor Cyan
    } else {
        Write-Host "[警告] 未找到 docker/.env.docker.example，无法自动生成 docker/.env.docker，请手动创建。" -ForegroundColor Yellow
    }
}

# 以「无 BOM 的 UTF-8」写回，避免给 .env 引入 BOM 影响解析
function Set-UnbomUtf8File {
    param([string]$Path, [string]$Text)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

# 替换（缺失时追加）指定文件中的 MYSQL_PASSWORD 行（不打印明文）
function Set-EnvPassword {
    param([string]$Path, [string]$Password)
    $text = [System.IO.File]::ReadAllText($Path)
    if ($text -match '(?m)^MYSQL_PASSWORD=') {
        $text = [regex]::Replace($text, '(?m)^MYSQL_PASSWORD=.*$', { param($m) "MYSQL_PASSWORD=$Password" })
    } else {
        if ($text.Length -gt 0 -and -not $text.EndsWith("`n")) { $text += "`n" }
        $text += "MYSQL_PASSWORD=$Password`n"
    }
    Set-UnbomUtf8File -Path $Path -Text $text
}

$randPwd = ''
if ($genEnv) {
    # 20 位随机密码（大小写字母 + 数字）
    $randPwd = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 20 | ForEach-Object { [char]$_ })
    Set-EnvPassword -Path $envFile -Password $randPwd
    Write-Host "[自举] 已生成 20 位随机 MySQL 密码并写入 .env" -ForegroundColor Cyan
}

if ($genDockerEnv -and (Test-Path -LiteralPath $dockerEnvFile -PathType Leaf)) {
    if ($genEnv) {
        Set-EnvPassword -Path $dockerEnvFile -Password $randPwd
    } else {
        # .env 已存在（用户真实密钥），沿用其中密码，保证两处一致
        $existingPwd = ''
        $mm = [regex]::Match([System.IO.File]::ReadAllText($envFile), '(?m)^MYSQL_PASSWORD=(.*)$')
        if ($mm.Success) { $existingPwd = $mm.Groups[1].Value.Trim() }
        if ($existingPwd -ne '') { Set-EnvPassword -Path $dockerEnvFile -Password $existingPwd }
    }
    Write-Host "[自举] 已将同一 MySQL 密码同步写入 docker/.env.docker" -ForegroundColor Cyan
}

if ($genEnv -or $genDockerEnv) {
    Write-Host ""
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan
    Write-Host "  环境文件自举完成，涉及的配置文件："
    Write-Host "    - .env"
    Write-Host "    - docker\.env.docker"
    Write-Host "  MySQL 密码已在以上两个文件中保持一致。"
    Write-Host "  [注意] LLM / 搜索 / 知识库 的 API Key 仍是占位符，服务可正常启动，"
    Write-Host "         但联网检索与大模型功能需在以上两个文件中填入真实值。"
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan
    Write-Host ""
}

function Test-DockerCli {
    return [bool](Get-Command docker -ErrorAction SilentlyContinue)
}

function Test-DockerRunning {
    docker info *> $null
    return ($LASTEXITCODE -eq 0)
}

# ---------- 0. 检查 Docker 是否安装 ----------
if (-not (Test-DockerCli)) {
    Write-Host "[错误] 未检测到 Docker 命令。请先安装 Docker Desktop。" -ForegroundColor Red
    Write-Host "       https://www.docker.com/products/docker-desktop/"
    exit 1
}

# ---------- 1. 检查 Docker 守护进程 ----------
if (-not (Test-DockerRunning)) {
    Write-Host "[提示] Docker 未运行，尝试启动 Docker Desktop ..." -ForegroundColor Yellow
    $dd = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path -LiteralPath $dd) {
        Start-Process -FilePath $dd | Out-Null
    } else {
        Write-Host "[错误] 未找到 Docker Desktop，请手动启动后重试。" -ForegroundColor Red
        exit 1
    }
    Write-Host "[等待] 等待 Docker 守护进程就绪（最长 180 秒）..."
    $ok = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-DockerRunning) { $ok = $true; break }
        Start-Sleep -Seconds 3
    }
    if (-not $ok) {
        Write-Host "[错误] 等待 Docker 超时，请手动打开 Docker Desktop 后重试。" -ForegroundColor Red
        exit 1
    }
}
Write-Host "[OK] Docker 已就绪。" -ForegroundColor Green

# ---------- 2. 构建并启动 ----------
Write-Host "[1/3] 构建并启动容器（首次构建需 3-8 分钟）..." -ForegroundColor Yellow
docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] 容器启动失败，请查看上方日志。" -ForegroundColor Red
    exit 1
}

# ---------- 3. 等待 MySQL 健康 ----------
Write-Host "[2/3] 等待 MySQL 初始化 ..." -ForegroundColor Yellow
$hs = ''
for ($i = 0; $i -lt 60; $i++) {
    $hs = (docker inspect -f '{{.State.Health.Status}}' das-mysql 2>$null)
    if ($hs -eq 'healthy') { break }
    Start-Sleep -Seconds 3
}
if ($hs -ne 'healthy') {
    Write-Host "[警告] MySQL 健康检查等待超时，继续检查其它服务 ..." -ForegroundColor Yellow
} else {
    Write-Host "[OK] MySQL 状态: healthy" -ForegroundColor Green
}

# ---------- 4. 输出 ----------
Write-Host "[3/3] 当前服务状态:" -ForegroundColor Yellow
docker compose ps

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  启动成功！请在浏览器中访问:"
Write-Host ""
Write-Host "    前端界面   http://localhost:8080" -ForegroundColor Green
Write-Host "    后端 API   http://localhost:8000/docs" -ForegroundColor Green
Write-Host "    认证服务   http://localhost:8001/docs" -ForegroundColor Green
Write-Host "    MySQL      127.0.0.1:3307  (root / 见 .env 中的 MYSQL_PASSWORD)"
Write-Host ""
Write-Host "  停止服务:  docker compose down"
Write-Host "  查看日志:  docker compose logs -f"
Write-Host "==================================================" -ForegroundColor Cyan
