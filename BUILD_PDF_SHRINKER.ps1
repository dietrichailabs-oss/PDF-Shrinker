[CmdletBinding()]
param(
    [string]$AppVersion = "1.0.1"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$AppName = "PDF Shrinker"
$Publisher = "Dietrich AI Labs"
$ExeName = "PDF_Shrinker.exe"
$InstallerName = "PDF_Shrinker_Setup_$AppVersion.exe"
$CertificateSubject = "CN=Dietrich AI Labs"

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath"
    }
}

function Copy-ProjectFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Missing source file: $Source"
    }

    $SourceFull = [IO.Path]::GetFullPath($Source)
    $DestinationFull = [IO.Path]::GetFullPath($Destination)
    if ($SourceFull -ne $DestinationFull) {
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
    }
}

function Find-InnoCompiler {
    $KnownPaths = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    )

    foreach ($Path in $KnownPaths) {
        if ($Path -and (Test-Path -LiteralPath $Path)) {
            return $Path
        }
    }

    $Command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }

    foreach ($Root in @(
        "$env:LOCALAPPDATA\Programs",
        "$env:ProgramFiles",
        "${env:ProgramFiles(x86)}"
    )) {
        if (-not $Root -or -not (Test-Path -LiteralPath $Root)) {
            continue
        }

        $Found = Get-ChildItem -LiteralPath $Root -Filter "ISCC.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($Found) {
            return $Found.FullName
        }
    }

    return $null
}

function Get-CodeSigningCertificate {
    param([string]$Subject)

    $Certificate = Get-ChildItem "Cert:\CurrentUser\My" -CodeSigningCert -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Subject -eq $Subject -and
            $_.HasPrivateKey -and
            $_.NotAfter -gt (Get-Date).AddDays(30)
        } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1

    if ($Certificate) {
        Write-Host "Reusing certificate $($Certificate.Thumbprint)" -ForegroundColor Green
        return $Certificate
    }

    Write-Host "Creating a self-signed Dietrich AI Labs certificate..." -ForegroundColor Yellow
    return New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $Subject `
        -FriendlyName "Dietrich AI Labs Code Signing" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeyAlgorithm RSA `
        -KeyLength 3072 `
        -HashAlgorithm SHA256 `
        -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddYears(5)
}

function Sign-File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Certificate
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Cannot sign missing file: $Path"
    }

    Write-Host "Signing $(Split-Path $Path -Leaf)..." -ForegroundColor Yellow
    Set-AuthenticodeSignature `
        -LiteralPath $Path `
        -Certificate $Certificate `
        -HashAlgorithm SHA256 `
        -IncludeChain All | Out-Null

    $Signature = Get-AuthenticodeSignature -LiteralPath $Path
    if (-not $Signature.SignerCertificate) {
        throw "No Authenticode signature was found after signing: $Path"
    }
    if ($Signature.SignerCertificate.Thumbprint -ne $Certificate.Thumbprint) {
        throw "Unexpected signing certificate on: $Path"
    }

    return $Signature
}

$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Desktop = [Environment]::GetFolderPath("Desktop")
$Project = Join-Path $Desktop "Marks Apps\PDF Shrinker"
$Build = Join-Path $Project "build"
$Dist = Join-Path $Project "dist"
$Release = Join-Path $Project "Release"
$Venv = Join-Path $Project ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Log = Join-Path $Project "LAST_BUILD_LOG.txt"

$AppScript = Join-Path $Project "pdf_shrinker.py"
$IconScript = Join-Path $Project "make_icon.py"
$Icon = Join-Path $Project "pdf_shrinker.ico"
$Requirements = Join-Path $Project "requirements.txt"
$InnoScript = Join-Path $Project "PDF_Shrinker_Installer.iss"
$BuiltExe = Join-Path $Dist $ExeName
$PortableExe = Join-Path $Release "PDF_Shrinker_Portable_$AppVersion.exe"
$InstallerExe = Join-Path $Release $InstallerName
$PublicCertificate = Join-Path $Release "Dietrich_AI_Labs_Code_Signing.cer"
$SignatureReport = Join-Path $Release "SIGNATURE_REPORT.txt"
$Checksums = Join-Path $Release "SHA256_CHECKSUMS.txt"
$SourceZip = Join-Path $Release "PDF_Shrinker_GitHub_Source_$AppVersion.zip"
$CoworkerZip = Join-Path $Release "PDF_Shrinker_Coworker_Package_$AppVersion.zip"

New-Item -ItemType Directory -Path $Project -Force | Out-Null
New-Item -ItemType Directory -Path $Release -Force | Out-Null

try {
    Start-Transcript -LiteralPath $Log -Force | Out-Null
} catch {}

try {
    Write-Host ""
    Write-Host "=================================================" -ForegroundColor Green
    Write-Host " PDF SHRINKER SELF-SIGNED RELEASE BUILD" -ForegroundColor Green
    Write-Host "=================================================" -ForegroundColor Green
    Write-Host "Source:  $SourceRoot"
    Write-Host "Project: $Project"
    Write-Host "Release: $Release"

    Write-Step "Preparing Desktop\Marks Apps\PDF Shrinker"

    $ProjectFiles = @(
        "pdf_shrinker.py",
        "make_icon.py",
        "requirements.txt",
        "PDF_Shrinker_Installer.iss",
        "README.md",
        "NOTICE.txt",
        ".gitignore",
        "RUN_BUILD.bat",
        "BUILD_PDF_SHRINKER.ps1"
    )

    foreach ($Name in $ProjectFiles) {
        Copy-ProjectFile `
            -Source (Join-Path $SourceRoot $Name) `
            -Destination (Join-Path $Project $Name)
    }

    $SourceAssets = Join-Path $SourceRoot "assets"
    $ProjectAssets = Join-Path $Project "assets"
    if (Test-Path -LiteralPath $SourceAssets) {
        New-Item -ItemType Directory -Path $ProjectAssets -Force | Out-Null
        Copy-Item -Path (Join-Path $SourceAssets "*") -Destination $ProjectAssets -Force
    }

    Write-Step "Preparing Python environment"

    if (-not (Test-Path -LiteralPath $Python)) {
        $Launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
        $SystemPython = Get-Command "python.exe" -ErrorAction SilentlyContinue
        if ($Launcher) {
            Invoke-Native $Launcher.Source @("-3", "-m", "venv", $Venv)
        }
        elseif ($SystemPython) {
            Invoke-Native $SystemPython.Source @("-m", "venv", $Venv)
        }
        else {
            throw "Python 3 was not found. Install Python 3.11 or newer."
        }
    }

    Invoke-Native $Python @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
    Invoke-Native $Python @(
        "-m", "pip", "install", "--upgrade",
        "-r", $Requirements,
        "pyinstaller",
        "pyinstaller-hooks-contrib"
    )

    Write-Step "Generating the Windows icon"
    Invoke-Native $Python @($IconScript)
    if (-not (Test-Path -LiteralPath $Icon)) {
        throw "Icon generation failed: $Icon"
    }

    Write-Step "Cleaning previous build output"
    foreach ($Folder in @($Build, $Dist)) {
        if (Test-Path -LiteralPath $Folder) {
            Remove-Item -LiteralPath $Folder -Recurse -Force
        }
    }
    foreach ($File in @(
        $PortableExe,
        $InstallerExe,
        $PublicCertificate,
        $SignatureReport,
        $Checksums,
        $SourceZip,
        $CoworkerZip,
        (Join-Path $Project "PDF_Shrinker.spec")
    )) {
        if (Test-Path -LiteralPath $File) {
            Remove-Item -LiteralPath $File -Force
        }
    }

    Write-Step "Building the standalone Windows EXE"
    Invoke-Native $Python @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "PDF_Shrinker",
        "--icon", $Icon,
        "--add-data", "$Icon;.",
        "--collect-all", "tkinterdnd2",
        $AppScript
    )

    if (-not (Test-Path -LiteralPath $BuiltExe)) {
        throw "PyInstaller did not create: $BuiltExe"
    }

    Write-Step "Creating or reusing the signing certificate"
    $Certificate = Get-CodeSigningCertificate -Subject $CertificateSubject
    if (-not $Certificate) {
        throw "The code-signing certificate could not be created."
    }

    Export-Certificate `
        -Cert $Certificate `
        -FilePath $PublicCertificate `
        -Type CERT `
        -Force | Out-Null

    Write-Step "Signing the application"
    $AppSignature = Sign-File -Path $BuiltExe -Certificate $Certificate
    Copy-Item -LiteralPath $BuiltExe -Destination $PortableExe -Force

    Write-Step "Finding Inno Setup"
    $ISCC = Find-InnoCompiler
    if (-not $ISCC) {
        throw "Inno Setup 6 or 7 was not found. The signed portable EXE is available at $PortableExe"
    }
    Write-Host "Using $ISCC" -ForegroundColor Green

    Write-Step "Building the installer"
    Invoke-Native $ISCC @($InnoScript)
    if (-not (Test-Path -LiteralPath $InstallerExe)) {
        throw "Inno Setup did not create: $InstallerExe"
    }

    Write-Step "Signing the installer"
    $InstallerSignature = Sign-File -Path $InstallerExe -Certificate $Certificate

    @"
PDF Shrinker $AppVersion
AUTHENTICODE SIGNATURE REPORT
=============================

Certificate subject: $($Certificate.Subject)
Certificate thumbprint: $($Certificate.Thumbprint)
Valid from: $($Certificate.NotBefore)
Expires: $($Certificate.NotAfter)

Portable EXE status on this computer: $($AppSignature.Status)
Installer EXE status on this computer: $($InstallerSignature.Status)

The files contain Authenticode signatures. Because this certificate is
self-signed, another computer may still display SmartScreen or Unknown
Publisher warnings until the certificate is explicitly trusted.
"@ | Set-Content -LiteralPath $SignatureReport -Encoding UTF8

    Write-Step "Creating release packages"
    $SourcePackage = Join-Path $Release "_source_package"
    $CoworkerPackage = Join-Path $Release "_coworker_package"
    foreach ($Folder in @($SourcePackage, $CoworkerPackage)) {
        if (Test-Path -LiteralPath $Folder) {
            Remove-Item -LiteralPath $Folder -Recurse -Force
        }
        New-Item -ItemType Directory -Path $Folder -Force | Out-Null
    }

    foreach ($Name in $ProjectFiles) {
        Copy-Item -LiteralPath (Join-Path $Project $Name) -Destination $SourcePackage -Force
    }
    Copy-Item -LiteralPath $Icon -Destination $SourcePackage -Force
    if (Test-Path -LiteralPath $ProjectAssets) {
        Copy-Item -LiteralPath $ProjectAssets -Destination $SourcePackage -Recurse -Force
    }

    Copy-Item -LiteralPath $InstallerExe -Destination $CoworkerPackage -Force
    Copy-Item -LiteralPath $PublicCertificate -Destination $CoworkerPackage -Force
    Copy-Item -LiteralPath $SignatureReport -Destination $CoworkerPackage -Force

    Compress-Archive -Path (Join-Path $SourcePackage "*") -DestinationPath $SourceZip -CompressionLevel Optimal
    Compress-Archive -Path (Join-Path $CoworkerPackage "*") -DestinationPath $CoworkerZip -CompressionLevel Optimal

    Remove-Item -LiteralPath $SourcePackage -Recurse -Force
    Remove-Item -LiteralPath $CoworkerPackage -Recurse -Force

    Write-Step "Writing SHA256 checksums"
    $HashFiles = @(
        $PortableExe,
        $InstallerExe,
        $SourceZip,
        $CoworkerZip,
        $PublicCertificate,
        $SignatureReport
    )

    $Lines = @(
        "PDF Shrinker $AppVersion SHA256 Checksums",
        "==========================================",
        ""
    )
    foreach ($File in $HashFiles) {
        $Lines += (Split-Path $File -Leaf)
        $Lines += (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash
        $Lines += ""
    }
    $Lines | Set-Content -LiteralPath $Checksums -Encoding UTF8

    @"
PDF Shrinker $AppVersion build completed successfully.
Completed: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

Signed portable EXE:
$PortableExe

Signed installer EXE:
$InstallerExe

GitHub source ZIP:
$SourceZip

Coworker ZIP:
$CoworkerZip
"@ | Set-Content -LiteralPath (Join-Path $Release "BUILD_COMPLETE.txt") -Encoding UTF8

    Write-Host ""
    Write-Host "=================================================" -ForegroundColor Green
    Write-Host " BUILD COMPLETE" -ForegroundColor Green
    Write-Host "=================================================" -ForegroundColor Green
    Write-Host "Installer: $InstallerExe"
    Write-Host "Portable:  $PortableExe"
    Write-Host "Source:    $SourceZip"
    Write-Host "Coworker:  $CoworkerZip"
    Write-Host ""
    Write-Host "Self-signing does not automatically remove SmartScreen warnings." -ForegroundColor Yellow

    Start-Process explorer.exe -ArgumentList "`"$Release`""
}
catch {
    Write-Host ""
    Write-Host "BUILD FAILED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Log: $Log" -ForegroundColor Yellow
    Read-Host "Press Enter to close"
    exit 1
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
