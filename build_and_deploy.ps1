# =============================================================================
# AgentSociety2 - Build, Push DockerHub & Portainer Production Deploy Pipeline
# Tự động đóng gói Backend Runtime + Frontend Gateway, đẩy lên DockerHub & cập nhật Local / Portainer
# =============================================================================

param (
    [switch]$SkipPush = $false,
    [switch]$SkipBuild = $false,
    [switch]$AutoDeployProd = $false,
    [switch]$LocalOnly = $false,
    [switch]$NonInteractive = $false
)

[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "AgentSociety2 - Build, Push & Portainer Deploy Pipeline"

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "   AgentSociety2 - Build, Push DockerHub & Portainer Deploy" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host ""

$rootDir = $PSScriptRoot
if (-not $rootDir) {
    $rootDir = Get-Location
}

# 1. Tim va nap file cau hinh (Uu tien portainer.env, sau do toi .env)
$envFile = Join-Path $rootDir "portainer.env"
if (-not (Test-Path $envFile)) {
    $envFile = Join-Path $rootDir ".env"
}

if (-not (Test-Path $envFile)) {
    Write-Host "[LOI] Khong tim thay file portainer.env hoac .env tai $rootDir!" -ForegroundColor Red
    Write-Host " -> Chay lenh sau roi dien cac thong tin bi mat:" -ForegroundColor Yellow
    Write-Host "    Copy-Item portainer.env.example portainer.env" -ForegroundColor Cyan
    exit 1
}

$envConfig = @{}
Get-Content $envFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#")) {
        $idx = $line.IndexOf("=")
        if ($idx -gt 0) {
            $key = $line.Substring(0, $idx).Trim()
            $rawVal = $line.Substring($idx + 1).Trim()
            if (($rawVal.StartsWith('"') -and $rawVal.EndsWith('"')) -or ($rawVal.StartsWith("'") -and $rawVal.EndsWith("'"))) {
                $val = $rawVal.Substring(1, $rawVal.Length - 2)
            } else {
                $commentIdx = $rawVal.IndexOf("#")
                if ($commentIdx -ge 0) {
                    $rawVal = $rawVal.Substring(0, $commentIdx).Trim()
                }
                $val = $rawVal.Trim('"').Trim("'")
            }
            $envConfig[$key] = $val
        }
    }
}

$repo = if ($envConfig["DOCKER_IMAGE_REPO"]) { $envConfig["DOCKER_IMAGE_REPO"] } else { "dungnt118/freepbx" }
$runtimeTag = if ($envConfig["AGENTSOCIETY_RUNTIME_TAG"]) { $envConfig["AGENTSOCIETY_RUNTIME_TAG"] } else { "agentsociety2-runtime" }
$gatewayTag = if ($envConfig["AGENTSOCIETY_GATEWAY_TAG"]) { $envConfig["AGENTSOCIETY_GATEWAY_TAG"] } else { "agentsociety2-gateway" }
$runtimeImage = if ($envConfig["AGENTSOCIETY_RUNTIME_IMAGE"]) { $envConfig["AGENTSOCIETY_RUNTIME_IMAGE"] } else { "$($repo):$($runtimeTag)" }
$gatewayImage = if ($envConfig["AGENTSOCIETY_GATEWAY_IMAGE"]) { $envConfig["AGENTSOCIETY_GATEWAY_IMAGE"] } else { "$($repo):$($gatewayTag)" }

$username = if ($envConfig["DOCKERHUB_USERNAME"]) { $envConfig["DOCKERHUB_USERNAME"] } else { "dungnt118" }
$token = $envConfig["DOCKERHUB_TOKEN"]

$webPort = if ($envConfig["AGENTSOCIETY_WEB_PORT"]) { $envConfig["AGENTSOCIETY_WEB_PORT"] } else { "5173" }
$apiPort = if ($envConfig["AGENTSOCIETY_API_PORT"]) { $envConfig["AGENTSOCIETY_API_PORT"] } else { "8001" }
$backendToken = $envConfig["BACKEND_TOKEN"]

$portainerUrl = if ($envConfig["PORTAINER_URL"]) { $envConfig["PORTAINER_URL"].TrimEnd("/") } else { "https://portainer.demego.vn" }
$portainerToken = $envConfig["PORTAINER_ACCESS_TOKEN"]
$portainerEndpointId = if ($envConfig["PORTAINER_ENDPOINT_ID"]) { [int]$envConfig["PORTAINER_ENDPOINT_ID"] } else { 3 }
$portainerStackId = if ($envConfig["PORTAINER_STACK_ID"]) { $envConfig["PORTAINER_STACK_ID"].Trim() } else { "" }
$portainerStackName = if ($envConfig["PORTAINER_STACK_NAME"]) { $envConfig["PORTAINER_STACK_NAME"] } else { "agentsociety2" }

Write-Host "[THONG TIN CAU HINH]" -ForegroundColor Yellow
Write-Host " - File cau hinh:       $envFile"
Write-Host " - DockerHub Username:  $username"
Write-Host " - Runtime Image:       $runtimeImage"
Write-Host " - Gateway Image:       $gatewayImage"
Write-Host " - Web UI Port:         http://localhost:$webPort"
Write-Host " - Backend API Port:    http://localhost:$apiPort"
if ($portainerUrl) {
    $stackDisplay = if ($portainerStackId) { "#$portainerStackId" } else { "(Chua nhap - de trong)" }
    Write-Host " - Portainer Server:    $portainerUrl (Stack: $portainerStackName | StackId: $stackDisplay | Endpoint: $portainerEndpointId)"
}
Write-Host ""

# 2. Kiem tra Docker Daemon
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[LOI] Docker daemon chua khoi dong hoac chua chay!" -ForegroundColor Red
    Write-Host "Vui long mo Docker Desktop truoc khi chay script nay." -ForegroundColor Yellow
    if (-not $NonInteractive) { Read-Host "Nhan Enter de thoat..." }
    exit 1
}

# 3. Dang nhap DockerHub bang Token
if ($token -and $username -and -not $SkipPush) {
    Write-Host "[1/4] Dang dang nhap DockerHub voi tai khoan $username..." -ForegroundColor Cyan
    $token | docker login -u $username --password-stdin
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Dang nhap DockerHub thanh cong!" -ForegroundColor Green
    } else {
        Write-Host "[CANH BAO] Dang nhap bang token khong thanh cong. Su dung phien dang nhap hien tai tren Docker Desktop." -ForegroundColor Yellow
    }
} else {
    Write-Host "[1/4] Bo qua dang nhap DockerHub (SkipPush hoac chua co token)." -ForegroundColor Yellow
}
Write-Host ""

# 4. Build Docker Images (Runtime Backend & Frontend Gateway)
if (-not $SkipBuild) {
    $env:DOCKER_BUILDKIT = 1
    $runtimeDockerfile = Join-Path $rootDir "docker\Dockerfile.runtime"
    $frontendDockerfile = Join-Path $rootDir "docker\Dockerfile.frontend"

    if (-not (Test-Path $runtimeDockerfile) -or -not (Test-Path $frontendDockerfile)) {
        Write-Host "[LOI] Khong tim thay docker/Dockerfile.runtime hoac docker/Dockerfile.frontend!" -ForegroundColor Red
        if (-not $NonInteractive) { Read-Host "Nhan Enter de thoat..." }
        exit 1
    }

    Write-Host "[2/4] Dang build Backend Runtime Image: $runtimeImage ..." -ForegroundColor Cyan
    docker build -t $runtimeImage -t "agentsociety2-runtime:local" -f $runtimeDockerfile $rootDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[LOI] Build Runtime Image '$runtimeImage' that bai!" -ForegroundColor Red
        if (-not $NonInteractive) { Read-Host "Nhan Enter de thoat..." }
        exit 1
    }
    Write-Host "[OK] Build Runtime Image thanh cong!" -ForegroundColor Green
    Write-Host ""

    Write-Host "[2/4] Dang build Frontend Gateway Image: $gatewayImage ..." -ForegroundColor Cyan
    docker build -t $gatewayImage -t "agentsociety-gateway:latest" -f $frontendDockerfile $rootDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[LOI] Build Gateway Image '$gatewayImage' that bai!" -ForegroundColor Red
        if (-not $NonInteractive) { Read-Host "Nhan Enter de thoat..." }
        exit 1
    }
    Write-Host "[OK] Build Gateway Image thanh cong!" -ForegroundColor Green
} else {
    Write-Host "[2/4] Bo qua buoc Build Docker Images theo tham so -SkipBuild." -ForegroundColor Yellow
}
Write-Host ""

# 5. Push Docker Images len DockerHub
$shouldSkipPush = $SkipPush.IsPresent -or $LocalOnly.IsPresent -or ($envConfig["SKIP_DOCKER_PUSH"] -eq "true") -or ($envConfig["AUTO_PUSH_DOCKERHUB"] -eq "false")
if (-not $shouldSkipPush) {
    Write-Host "[3/4] Dang day - Push Images len Docker Hub..." -ForegroundColor Cyan
    docker push $runtimeImage
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[LOI] Push '$runtimeImage' len Docker Hub that bai!" -ForegroundColor Red
        if (-not $NonInteractive) { Read-Host "Nhan Enter de thoat..." }
        exit 1
    }
    docker push $gatewayImage
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[LOI] Push '$gatewayImage' len Docker Hub that bai!" -ForegroundColor Red
        if (-not $NonInteractive) { Read-Host "Nhan Enter de thoat..." }
        exit 1
    }
    Write-Host "[OK] Push ca 2 images len Docker Hub thanh cong!" -ForegroundColor Green
} else {
    Write-Host "[3/4] Bo qua buoc Push Docker Hub theo cau hinh/tham so." -ForegroundColor Yellow
}
Write-Host ""

# 6. Trien khai Local tren Docker Desktop (Tuy chon)
$shouldDeployLocal = $false
if ($LocalOnly) {
    $shouldDeployLocal = $true
} elseif (-not $NonInteractive -and -not $AutoDeployProd) {
    $deployPrompt = "Ban co muon restart/cap nhat stack AgentSociety2 tren Docker Desktop (Local) khong? [Y/N] (Mac dinh: Y)"
    $userLocalResp = Read-Host -Prompt $deployPrompt
    if (-not $userLocalResp -or $userLocalResp.Trim().ToUpper() -eq "Y") {
        $shouldDeployLocal = $true
    }
}

if ($shouldDeployLocal) {
    $localCompose = Join-Path $rootDir "docker-compose.local.yml"
    $stackCompose = Join-Path $rootDir "portainer-stack.yml"
    $composeToUse = if (Test-Path $localCompose) { $localCompose } else { $stackCompose }
    $stackProjectName = if ($envConfig["COMPOSE_PROJECT_NAME"]) { $envConfig["COMPOSE_PROJECT_NAME"] } else { "agentsociety" }

    Write-Host "[Local] Dang khoi dong/cap nhat Stack '$stackProjectName' ($composeToUse)..." -ForegroundColor Cyan
    docker compose -p $stackProjectName -f $composeToUse --env-file $envFile up -d --remove-orphans
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Stack '$stackProjectName' da khoi chay thanh cong tren Docker Desktop!" -ForegroundColor Green
        Write-Host " - Web UI:          http://localhost:$webPort" -ForegroundColor Cyan
        Write-Host " - API HealthCheck: http://localhost:$apiPort/health" -ForegroundColor Cyan

        $hcHeaders = @{}
        if ($backendToken) {
            $hcHeaders["Authorization"] = "Bearer $backendToken"
        }
        $healthy = $false
        for ($i = 1; $i -le 30; $i++) {
            try {
                $hc = Invoke-RestMethod -Uri "http://127.0.0.1:$apiPort/health" -Headers $hcHeaders -Method Get -TimeoutSec 3 -ErrorAction Stop
                if ($hc) {
                    $healthy = $true
                    Write-Host " [OK] Backend HEALTHY sau $($i * 2) giay!" -ForegroundColor Green
                    break
                }
            } catch {}
            Start-Sleep -Seconds 2
        }
        if (-not $healthy) {
            Write-Host " [CANH BAO] Backend dang khoi tao trong nen. Kiem tra: docker compose -p $stackProjectName logs -f backend" -ForegroundColor Yellow
        }
        docker compose -p $stackProjectName -f $composeToUse --env-file $envFile ps
    } else {
        Write-Host "[LOI] Khong the khoi chay stack tren Docker Desktop!" -ForegroundColor Red
    }
} else {
    Write-Host "[Local] Bo qua buoc khoi chay tren Docker Desktop theo lua chon cua ban." -ForegroundColor Yellow
}
Write-Host ""

# 7. Trien khai Production qua Portainer API (Chi chay khi da cau hinh PORTAINER_STACK_ID)
if ($portainerUrl -and $portainerToken -and $portainerStackId -and -not $LocalOnly) {
    $shouldDeployProd = $false
    if ($AutoDeployProd) {
        $shouldDeployProd = $true
    } elseif (-not $NonInteractive) {
        $prodPrompt = "Ban co muon tu dong redeploy Stack '$portainerStackName' (#$portainerStackId) len Portainer Production khong? [Y/N] (Mac dinh: Y)"
        $userResp = Read-Host -Prompt $prodPrompt
        if (-not $userResp -or $userResp.Trim().ToUpper() -eq "Y") {
            $shouldDeployProd = $true
        }
    }

    if ($shouldDeployProd) {
        $deployScript = Join-Path $rootDir "deploy\portainer-deploy.mjs"
        if (Test-Path $deployScript) {
            Write-Host "[4/4] Dang chay script deploy Portainer (deploy/portainer-deploy.mjs)..." -ForegroundColor Cyan
            node $deployScript
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[LOI] Deploy Portainer that bai (ma loi $LASTEXITCODE)!" -ForegroundColor Red
                if (-not $NonInteractive) { Read-Host "Nhan Enter de thoat..." }
                exit $LASTEXITCODE
            }
        } else {
            Write-Host "[LOI] Khong tim thay deploy/portainer-deploy.mjs!" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "[Portainer] Bo qua buoc redeploy Portainer Production theo lua chon cua ban." -ForegroundColor Yellow
    }
} else {
    if ($LocalOnly) {
        Write-Host "[Portainer] Bo qua buoc redeploy Production vi dang o che do -LocalOnly." -ForegroundColor Yellow
    } else {
        Write-Host "[Portainer] PORTAINER_STACK_ID chua duoc cau hinh trong portainer.env -> Bo qua buoc redeploy Portainer Production." -ForegroundColor Yellow
        Write-Host " -> Ban co the copy truc tiep 'portainer-stack.yml' va 'portainer.env' de tao Stack tren Portainer Web UI, sau do dien PORTAINER_STACK_ID." -ForegroundColor Cyan
    }
}

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Green
Write-Host "   QUY TRINH BUILD & DEPLOY PIPELINE HOAN TAT!" -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green
if ($portainerUrl -and $portainerStackId -and -not $LocalOnly) {
    Write-Host "Link kiem tra Portainer: $portainerUrl/#!/$portainerEndpointId/docker/stacks/$portainerStackName?id=$portainerStackId&type=2" -ForegroundColor Cyan
}
if (-not $NonInteractive) {
    Read-Host "Nhan Enter de dong cua so..."
}
