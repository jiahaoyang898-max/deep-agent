# ==================================================
#  Deep Agent Search  -  一键启动 (PowerShell)
#  用法（在项目根目录）:
#      powershell -ExecutionPolicy Bypass -File .\start.ps1
#      powershell -ExecutionPolicy Bypass -File .\start.ps1 -FrontendOnly   # 只重建前端
# ==================================================
param(
    # 只重建并重启前端容器（改完前端代码后最快的迭代路径，不碰后端/数据库）
    [switch]$FrontendOnly
)

# 注意：不能用 'Stop'。PowerShell 5.1 会把 docker build 打印到 stderr 的进度
# 当作 NativeCommandError 异常，导致脚本在 `docker compose up -d --build` 处误终止
# （docker 实际是成功的，exit 0，只是 stderr 非空）。改为 'Continue'，所有 docker
# 调用的真实失败仍由紧随其后的 `if ($LASTEXITCODE -ne 0)` 判定，行为不变。
$ErrorActionPreference = 'Continue'
# 抑制 Invoke-WebRequest 的进度条，避免探活时刷屏
$ProgressPreference    = 'SilentlyContinue'

# ---------- 控制台编码：保证中文 Write-Host 不乱码 ----------
# 配合 start.bat 里的 chcp 65001，双保险。设置失败不影响主流程。
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding           = [System.Text.Encoding]::UTF8
} catch {
    # 某些非交互宿主不支持设置编码，忽略即可
}

# ---------- 探活防代理：localhost 必须直连，不走系统代理 ----------
$env:NO_PROXY = 'localhost,127.0.0.1'
$env:no_proxy = 'localhost,127.0.0.1'
try { [System.Net.WebRequest]::DefaultWebProxy = $null } catch { }

Set-Location -LiteralPath $PSScriptRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Deep Agent Search  -  一键启动 (Docker)" -ForegroundColor Cyan
if ($FrontendOnly) {
    Write-Host "  模式：只重建前端 (-FrontendOnly)" -ForegroundColor Cyan
}
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

# ---------- 查询端口被谁占用（返回描述数组）----------
# 端口冲突时 compose 只会报一句看不懂的 bind 错误，这里提前定位到进程。
function Get-PortOwner {
    param([int]$Port)
    $owners = @()
    try {
        $conns = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    } catch {
        $conns = @()
    }
    foreach ($c in $conns) {
        $name = "PID $($c.OwningProcess)"
        try {
            $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
            if ($p) { $name = "$($p.ProcessName) (PID $($c.OwningProcess))" }
        } catch {
            # 进程已退出或无权访问，保留 PID 形式
        }
        if ($owners -notcontains $name) { $owners += $name }
    }
    return $owners
}

# ---------- 端口预检：报出占用者，而不是等 compose 报错 ----------
function Test-Ports {
    param([int[]]$Ports)
    $hasConflict = $false
    foreach ($port in $Ports) {
        $owners = Get-PortOwner -Port $port
        if ($owners.Count -eq 0) { continue }
        $txt = $owners -join '、'
        $isDocker = $false
        foreach ($o in $owners) {
            if ($o -match 'docker|vmmem|wsl|com\.docker') { $isDocker = $true }
        }
        if ($isDocker) {
            # 多数情况是我方已有容器在跑，compose 会自行替换，不必惊慌
            Write-Host "[提示] 端口 $port 已被 Docker 相关进程占用（$txt），通常是已有容器在运行。" -ForegroundColor DarkGray
        } else {
            $hasConflict = $true
            Write-Host "[警告] 端口 $port 已被占用：$txt" -ForegroundColor Yellow
        }
    }
    if ($hasConflict) {
        Write-Host "       处理办法：关闭占用端口的程序，或修改 docker-compose.yml 里的端口映射。" -ForegroundColor Yellow
        Write-Host "       自行定位（以 8080 为例）：" -ForegroundColor Yellow
        Write-Host "         Get-NetTCPConnection -LocalPort 8080 -State Listen | Select-Object LocalPort,OwningProcess" -ForegroundColor Yellow
        Write-Host "         Get-Process -Id <上面输出的 PID>" -ForegroundColor Yellow
    }
}

# ---------- 磁盘空间预检（Docker Desktop 默认把镜像放在 C 盘）----------
function Test-FreeSpace {
    param([string]$DriveLetter, [double]$MinGB, [string]$Why)
    $free = $null
    try {
        $d = Get-PSDrive -Name $DriveLetter -ErrorAction Stop
        if ($d -and $d.Free -ne $null) { $free = [math]::Round($d.Free / 1GB, 1) }
    } catch {
        return  # 拿不到就不猜，直接跳过
    }
    if ($free -ne $null -and $free -lt $MinGB) {
        Write-Host "[警告] ${DriveLetter}: 盘可用空间仅 ${free} GB（建议 ≥ ${MinGB} GB）—— $Why" -ForegroundColor Yellow
        return $true
    }
    return $false
}

function Test-DiskSpace {
    $low = $false
    # Docker Desktop 的镜像/WSL 数据盘默认在系统盘（通常是 C:）
    $sysLetter = ''
    if ($env:SystemDrive -and $env:SystemDrive.Length -ge 1) { $sysLetter = $env:SystemDrive.Substring(0, 1).ToUpper() }
    if ($sysLetter -ne '') {
        if (Test-FreeSpace -DriveLetter $sysLetter -MinGB 5 -Why 'Docker Desktop 的镜像与 WSL 数据盘默认位于系统盘，空间不足会导致构建中断。') { $low = $true }
    }
    $projLetter = ''
    if ($PSScriptRoot -and $PSScriptRoot.Length -ge 1) { $projLetter = $PSScriptRoot.Substring(0, 1).ToUpper() }
    if ($projLetter -ne '' -and $projLetter -ne $sysLetter) {
        if (Test-FreeSpace -DriveLetter $projLetter -MinGB 2 -Why '项目目录（含 docker-data 数据卷）所在盘。') { $low = $true }
    }
    if ($low) {
        Write-Host "       查看占用：docker system df" -ForegroundColor Yellow
        Write-Host "       清理悬空镜像：docker image prune -a" -ForegroundColor Yellow
        Write-Host "       清理构建缓存：docker builder prune" -ForegroundColor Yellow
        Write-Host "       Docker Desktop：Settings → Resources → Disk image location 可迁移镜像位置。" -ForegroundColor Yellow
    }
}

# ---------- 单个 HTTP 探活（失败不抛异常，只返回结果）----------
function Invoke-HealthProbe {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSec  = 60,
        [int]$IntervalSec = 3
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        try {
            # -UseBasicParsing 是硬要求：否则 Windows PowerShell 会依赖 IE 引擎而报错
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 8 -ErrorAction Stop
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400) {
                Write-Host ("       [OK] {0} 已就绪（HTTP {1}，耗时 {2:N0}s）" -f $Name, $resp.StatusCode, $sw.Elapsed.TotalSeconds) -ForegroundColor Green
                return $true
            }
        } catch {
            # 还没起来，继续轮询；不让单次失败打断整个脚本
        }
        Start-Sleep -Seconds $IntervalSec
    }
    Write-Host ("       [失败] {0} 在 {1}s 内未就绪" -f $Name, $TimeoutSec) -ForegroundColor Red
    return $false
}

# ---------- 打印探活失败后的可执行建议 ----------
function Show-ProbeHelp {
    param([array]$Failed)
    Write-Host ""
    Write-Host "[提示] 以下服务暂未就绪，按序排查：" -ForegroundColor Yellow
    foreach ($f in $Failed) {
        Write-Host ("       - {0}（{1}）" -f $f.Name, $f.Url) -ForegroundColor Yellow
        Write-Host ("         查看日志：docker compose logs -f {0}" -f $f.Service) -ForegroundColor Yellow
    }
    Write-Host "       容器状态一览：docker compose ps"
    Write-Host "       重启单个服务：docker compose up -d --force-recreate <服务名>"
}

# ---------- compose 失败时抓取日志尾部，给出下一步 ----------
function Show-ComposeFailure {
    param([string]$Stage, [int]$ExitCode)
    Write-Host "[错误] ${Stage}失败（退出码 ${ExitCode}）。" -ForegroundColor Red
    Write-Host "       下面是 docker compose logs 末尾 20 行：" -ForegroundColor Yellow
    try { cmd /c "docker compose logs --tail 20" 2>$null } catch { }
    Write-Host ""
    Write-Host "       下一步：" -ForegroundColor Yellow
    Write-Host "         docker compose ps                  # 看哪个容器退出了"
    Write-Host "         docker compose logs -f             # 实时看全部日志"
    Write-Host "         docker compose build --progress=plain --no-cache <服务名>   # 构建失败时看完整输出"
    Write-Host "         docker system df ; docker builder prune                     # 怀疑磁盘不足时"
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

# ---------- 2. 预检：端口占用 + 磁盘空间 ----------
if ($FrontendOnly) {
    Test-Ports -Ports @(8080)
} else {
    Test-Ports -Ports @(8080, 8000, 8001, 3307)
}
Test-DiskSpace

$frontendProbe = @{ Name = '前端'; Url = 'http://localhost:8080/';    Service = 'frontend' }
$backendProbe  = @{ Name = '后端'; Url = 'http://localhost:8000/docs'; Service = 'backend'  }
$authProbe     = @{ Name = '认证'; Url = 'http://localhost:8001/docs'; Service = 'auth'     }

if ($FrontendOnly) {
    # ---------- 快速通道：只重建前端 ----------
    Write-Host "[1/2] 构建前端镜像（只构建 frontend）..." -ForegroundColor Yellow
    cmd /c "docker compose build frontend" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 前端镜像构建失败。查看完整构建输出：" -ForegroundColor Red
        Write-Host "       docker compose build --progress=plain --no-cache frontend"
        Write-Host "       若提示 no space left on device：docker builder prune"
        exit 1
    }

    Write-Host "[2/2] 重启前端容器 ..." -ForegroundColor Yellow
    cmd /c "docker compose up -d frontend" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Show-ComposeFailure -Stage '启动前端容器 ' -ExitCode $LASTEXITCODE
        exit 1
    }

    Write-Host "[探活] 前端服务 ..." -ForegroundColor Yellow
    $failed = @()
    try {
        $okFe = Invoke-HealthProbe -Name $frontendProbe.Name -Url $frontendProbe.Url -TimeoutSec 120 -IntervalSec 3
    } catch {
        $okFe = $false
        Write-Host "       [异常] 前端探活出错：$($_.Exception.Message)" -ForegroundColor Red
    }
    if (-not $okFe) { $failed += $frontendProbe }

    cmd /c "docker compose ps frontend" 2>$null

    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Cyan
    if ($failed.Count -eq 0) {
        Write-Host "  前端已重建完成！访问: http://localhost:8080" -ForegroundColor Green
    } else {
        Write-Host "  前端已重启，但探活未通过，请按下方提示排查：" -ForegroundColor Yellow
        Show-ProbeHelp -Failed $failed
    }
    Write-Host ""
    Write-Host "  查看前端日志:  docker compose logs -f frontend"
    Write-Host "  需要全量重建:  .\start.ps1"
    Write-Host "==================================================" -ForegroundColor Cyan
    exit 0
}

# ---------- 3. 构建并启动 ----------
Write-Host "[1/4] 构建并启动容器（首次构建需 3-8 分钟）..." -ForegroundColor Yellow
cmd /c "docker compose up -d --build" 2>$null
if ($LASTEXITCODE -ne 0) {
    Show-ComposeFailure -Stage '构建并启动容器 ' -ExitCode $LASTEXITCODE
    exit 1
}

# ---------- 4. 等待 MySQL 健康 ----------
Write-Host "[2/4] 等待 MySQL 初始化 ..." -ForegroundColor Yellow
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

# ---------- 5. 服务探活（真实 HTTP 请求，而不是只看 compose ps）----------
Write-Host "[3/4] 服务探活（每个服务最长 60 秒）..." -ForegroundColor Yellow
$failed = @()
foreach ($p in @($frontendProbe, $backendProbe, $authProbe)) {
    try {
        $ok = Invoke-HealthProbe -Name $p.Name -Url $p.Url -TimeoutSec 120 -IntervalSec 3
    } catch {
        $ok = $false
        Write-Host "       [异常] $($p.Name) 探活出错：$($_.Exception.Message)" -ForegroundColor Red
    }
    if (-not $ok) { $failed += $p }
}
if ($failed.Count -eq 0) {
    Write-Host "[OK] 三个服务全部探活通过。" -ForegroundColor Green
} else {
    Show-ProbeHelp -Failed $failed
}

# ---------- 6. 输出 ----------
Write-Host "[4/4] 当前服务状态:" -ForegroundColor Yellow
cmd /c "docker compose ps" 2>$null

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
if ($failed.Count -eq 0) {
    Write-Host "  启动成功！请在浏览器中访问:"
} else {
    Write-Host "  启动完成，但有服务未通过探活，请先看上方提示：" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "    前端界面   http://localhost:8080" -ForegroundColor Green
Write-Host "    后端 API   http://localhost:8000/docs" -ForegroundColor Green
Write-Host "    认证服务   http://localhost:8001/docs" -ForegroundColor Green
Write-Host "    MySQL      127.0.0.1:3307  (root / 见 .env 中的 MYSQL_PASSWORD)"
Write-Host ""
Write-Host "  停止服务:  docker compose down"
Write-Host "  查看日志:  docker compose logs -f"
Write-Host "  只重建前端:  powershell -ExecutionPolicy Bypass -File .\start.ps1 -FrontendOnly"
Write-Host "==================================================" -ForegroundColor Cyan
