param([ValidateSet('check','apply','interactive')][string]$Mode='check',[string]$Approved='')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$ids=[ordered]@{python='Python.Python.3.12';node='OpenJS.NodeJS.LTS';chrome='Google.Chrome';ffmpeg='Gyan.FFmpeg';runtime='local'}
$impact=@{python='缺 Python 3.12 x64 时，包内制作、合成与导出脚本无法运行。';node='不能执行浏览器镜头的渲染驱动。';chrome='不能生成浏览器镜头的画面帧。';ffmpeg='不能编码、封装或核验最终 MP4。';runtime='当前版本的本地引擎与私有依赖尚未就绪，无法通过 film.cmd 制作。'}
function Find-Python {
    $candidates=@("$env:LOCALAPPDATA/Programs/Python/Python312/python.exe")
    if(Test-Path "$env:LOCALAPPDATA/CodeFilm/python312.path"){$candidates+=Get-Content "$env:LOCALAPPDATA/CodeFilm/python312.path" -Encoding UTF8 -TotalCount 1}
    $candidates+=@(Get-Command python.exe -All -ErrorAction SilentlyContinue | ForEach-Object Source)
    foreach($p in $candidates){
        if($p -and (Test-Path -LiteralPath $p -PathType Leaf) -and $p -notmatch '\\Microsoft\\WindowsApps\\python.exe$'){
            $v=& $p -B -c "import sys,platform;print(sys.executable if sys.version_info[:2]==(3,12) and platform.machine().lower() in ('amd64','x86_64') else '')"
            if($LASTEXITCODE -eq 0 -and $v){return $v}
        }
    }
    if(Get-Command py.exe -ErrorAction SilentlyContinue){
        $v=& py.exe -3.12-64 -B -c "import sys;print(sys.executable)" 2>$null
        if($LASTEXITCODE -eq 0){return $v}
    }
}
function Check {
    $script:py=Find-Python
    $nodeOK=$false
    if(Get-Command node.exe -ErrorAction SilentlyContinue){& node -e "let [a,b]=process.versions.node.split('.').map(Number);process.exit(+(a<22||(a==22&&b<12)))";$nodeOK=$LASTEXITCODE -eq 0}
    $browser=@($env:PUPPETEER_EXECUTABLE_PATH,"$env:ProgramFiles/Google/Chrome/Application/chrome.exe","$env:LOCALAPPDATA/Google/Chrome/Application/chrome.exe","${env:ProgramFiles(x86)}/Google/Chrome/Application/chrome.exe") | Where-Object {$_ -and (Test-Path -LiteralPath $_ -PathType Leaf)} | Select-Object -First 1
    $ff=$true
    foreach($name in 'ffmpeg','ffprobe'){if(Get-Command $name -ErrorAction SilentlyContinue){& $name -version >$null;if($LASTEXITCODE){$ff=$false}}else{$ff=$false}}
    $key=(Get-FileHash "$PSScriptRoot/engine.zip").Hash.Substring(0,24).ToLower()
    $root="$env:LOCALAPPDATA/CodeFilm/$key"
    $ready=$false
    if((Test-Path "$root/venv/Scripts/python.exe") -and (Test-Path "$root/node_modules/puppeteer/package.json") -and (Test-Path "$root/scripts/cut.py") -and (Test-Path "$env:LOCALAPPDATA/CodeFilm/python312.path")){
        $record=Get-Content "$env:LOCALAPPDATA/CodeFilm/python312.path" -Encoding UTF8 -TotalCount 1
        if($record -and (Test-Path -LiteralPath $record)){& "$root/venv/Scripts/python.exe" -B -c "import numpy,PIL.Image";$ready=$LASTEXITCODE -eq 0}
    }
    [ordered]@{python=[bool]$py;node=$nodeOK;chrome=[bool]$browser;ffmpeg=$ff;runtime=$ready}
}
function Report($state){
    $items=@(foreach($id in $ids.Keys){if(!$state[$id]){[ordered]@{id=$id;package=$ids[$id];impact=$impact[$id];source=$(if($id -eq 'runtime'){'随包文件，安装到当前用户缓存'}else{'winget，需要联网，可能出现系统授权提示'})}}})
    [ordered]@{ready=($items.Count -eq 0);missing=$items;winget=[bool](Get-Command winget -ErrorAction SilentlyContinue);available='可直接阅读 topics 说明、编写脚本、分镜和配乐方案。'} | ConvertTo-Json -Depth 4 -Compress
}
$state=Check
if($Mode -eq 'check'){Report $state;exit 0}
$allow=@($Approved -split ',' | ForEach-Object {$_.Trim().ToLower()} | Where-Object {$_})
if($Mode -eq 'interactive'){
    Report $state
    if(!($state.Values -contains $false)){exit 0}
    $answer=Read-Host '输入同意安装的缺项 ID，以英文逗号隔开；直接回车跳过'
    $allow=@($answer -split ',' | ForEach-Object {$_.Trim().ToLower()} | Where-Object {$_})
}
foreach($id in $allow){if(!$ids.Contains($id)){throw "Unknown component: $id"}}
foreach($id in $ids.Keys){
    if($state[$id] -or $allow -notcontains $id){continue}
    if($id -eq 'runtime'){
        $state=Check
        if(@('python','node','chrome','ffmpeg') | Where-Object {!$state[$_]}){Write-Host '本地引擎初始化暂缓，完整启动验证仍缺系统组件。';continue}
        & $py -X utf8 "$PSScriptRoot/film.py" install
        if($LASTEXITCODE){throw 'Runtime initialization failed'}
        [IO.File]::WriteAllText("$env:LOCALAPPDATA/CodeFilm/python312.path",$py,[Text.UTF8Encoding]::new($false))
    }else{
        if(!(Get-Command winget -ErrorAction SilentlyContinue)){throw "winget unavailable: $($ids[$id])"}
        & winget install --exact --id $ids[$id] --accept-package-agreements --accept-source-agreements
        if($LASTEXITCODE){throw "winget returned $LASTEXITCODE for $id"}
        $env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')+';'+$env:Path
    }
}
Report (Check)
