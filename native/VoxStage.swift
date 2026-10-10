import Cocoa
import WebKit
import Darwin

func L(_ zh: String, _ en: String) -> String {
    return (Locale.preferredLanguages.first ?? "en").hasPrefix("zh") ? zh : en
}

enum RuntimeError: LocalizedError {
    case failed(String)
    var errorDescription: String? { if case .failed(let message) = self { return message }; return nil }
}

final class RuntimeController {
    var process: Process?
    var stateURL: URL!
    var logHandle: FileHandle?
    var port = 0
    var token = UUID().uuidString + UUID().uuidString
    let resources: URL
    let data: URL
    let logs: URL
    var ownsGroup = false
    init() {
        resources = Bundle.main.resourceURL!
        let home = FileManager.default.homeDirectoryForCurrentUser
        let env = ProcessInfo.processInfo.environment
        data = env["VOXSTAGE_DATA_DIR"].map { URL(fileURLWithPath:$0) } ?? home.appendingPathComponent("Library/Application Support/VoxStage")
        logs = env["VOXSTAGE_LOG_DIR"].map { URL(fileURLWithPath:$0) } ?? home.appendingPathComponent("Library/Logs/VoxStage")
    }
    func start(lan: Bool = false) throws {
        try FileManager.default.createDirectory(at:data,withIntermediateDirectories:true)
        try FileManager.default.createDirectory(at:logs,withIntermediateDirectories:true)
        let id = UUID().uuidString
        stateURL = logs.appendingPathComponent("runtime-\(id).json")
        let log = logs.appendingPathComponent("runtime-\(id).log")
        FileManager.default.createFile(atPath:log.path,contents:nil,attributes:[.posixPermissions:0o600])
        logHandle = try FileHandle(forWritingTo:log)
        var env: [String:String] = [:]
        for name in ["HOME","USER","LOGNAME","TMPDIR","LANG","LC_ALL"] {
            env[name] = ProcessInfo.processInfo.environment[name]
        }
        env["PATH"] = "/usr/bin:/bin"
        env["VOXSTAGE_DATA_DIR"] = data.path
        env["VOXSTAGE_LOG_DIR"] = logs.path
        env["VOXSTAGE_DESKTOP_STATE"] = stateURL.path
        env["VOXSTAGE_NATIVE_TOKEN"] = token
        env["VOXSTAGE_FFMPEG"] = resources.appendingPathComponent("bin/ffmpeg").path
        env["VOXSTAGE_ROLE_SERVER"] = resources.appendingPathComponent("bin/llama-server").path
        env["VOXSTAGE_WHISPER_CLI"] = resources.appendingPathComponent("bin/whisper-cli").path
        env["HF_HOME"] = data.appendingPathComponent("hf-cache").path
        env["HF_HUB_OFFLINE"] = "1"
        env["HF_HUB_DISABLE_TELEMETRY"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        let child = Process()
        child.executableURL = resources.appendingPathComponent("python/bin/python3")
        child.currentDirectoryURL = resources.appendingPathComponent("app")
        child.arguments = ["-B","-m","runtime.desktop"] + (lan ? ["--lan"] : [])
        child.environment = env
        child.standardOutput = logHandle
        child.standardError = logHandle
        try child.run()
        process = child
    }
    func state() throws -> [String:Any]? {
        guard let process = process else { return nil }
        if !process.isRunning { throw RuntimeError.failed(L("本地服务未启动，请查看日志。","The local service did not start. See the logs.")) }
        if getpgid(process.processIdentifier) == process.processIdentifier { ownsGroup = true }
        guard let bytes = try? Data(contentsOf:stateURL),
              let value = try? JSONSerialization.jsonObject(with:bytes) as? [String:Any],
              value["app"] as? String == "VoxStage", value["pid"] as? Int == Int(process.processIdentifier),
              let actualPort = value["port"] as? Int else { return nil }
        port = actualPort
        return value
    }
    func request(_ path: String, body: [String:Any]? = nil) throws -> [String:Any] {
        let url = URL(string:"http://127.0.0.1:\(port)/api"+path)!
        var req = URLRequest(url:url)
        req.timeoutInterval = 30
        req.setValue("1",forHTTPHeaderField:"X-VoxStage")
        req.setValue(token,forHTTPHeaderField:"X-VoxStage-Native")
        if let body = body {
            req.httpMethod = "POST"
            req.setValue("application/json",forHTTPHeaderField:"Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject:body)
        }
        let done = DispatchSemaphore(value:0)
        var result: [String:Any]?
        var failure: Error?
        let task = URLSession.shared.dataTask(with:req) { data,response,error in
            defer { done.signal() }
            if let error = error { failure=error;return }
            guard let data=data,let value=try? JSONSerialization.jsonObject(with:data) as? [String:Any] else {
                failure=RuntimeError.failed(L("本地服务回应无法读取。","Cannot read the local service response."));return
            }
            if let response=response as? HTTPURLResponse, response.statusCode != 200 {
                failure=RuntimeError.failed(value["detail"] as? String ?? L("请求未完成。","Request incomplete."));return
            }
            result=value
        }
        task.resume()
        if done.wait(timeout:.now()+35) == .timedOut { task.cancel();throw RuntimeError.failed(L("本地服务回应超时。","Local service response timed out.")) }
        if let error=failure { throw error }
        return result ?? [:]
    }
    func stop() {
        guard let child=process else { return }
        let pid=child.processIdentifier
        if getpgid(pid)==pid { ownsGroup=true }
        if ownsGroup { _ = kill(-pid,SIGTERM) }
        else if child.isRunning { child.terminate() }
        let limit=Date().addingTimeInterval(6)
        while child.isRunning && Date()<limit { usleep(100_000) }
        // Kill the owned group even if the supervisor exited before an inference child.
        if ownsGroup { _ = kill(-pid,SIGKILL) }
        else if child.isRunning { _ = kill(pid,SIGKILL) }
        child.waitUntilExit()
        try? logHandle?.close()
        if let stateURL=stateURL { try? FileManager.default.removeItem(at:stateURL) }
        process=nil;ownsGroup=false;port=0
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
    let runtime = RuntimeController()
    var window: NSWindow!
    var web: WKWebView!
    var timer: Timer?
    var deadline: Date!
    var lan=false
    var lanItem: NSMenuItem!
    var ready=false
    func applicationDidFinishLaunching(_ notification:Notification) {
        makeMenu()
        let configuration=WKWebViewConfiguration()
        configuration.userContentController.add(self,name:"voxstage")
        web=WKWebView(frame:.zero,configuration:configuration)
        web.navigationDelegate=self;web.uiDelegate=self
        window=NSWindow(contentRect:NSRect(x:0,y:0,width:1160,height:780),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
        window.title="VoxStage";window.minSize=NSSize(width:760,height:520)
        window.contentView=web;window.center();window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps:true)
        web.loadHTMLString("<html><body style='font:18px -apple-system;padding:40px'>"+L("正在启动 VoxStage…","Starting VoxStage…")+"</body></html>",baseURL:nil)
        start()
    }
    func makeMenu() {
        let menu=NSMenu()
        let item=NSMenuItem();menu.addItem(item)
        let app=NSMenu();item.submenu=app
        app.addItem(withTitle:L("关于 VoxStage","About VoxStage"),action:#selector(about),keyEquivalent:"")
        app.addItem(withTitle:L("查看第三方许可与源码","Third-party licenses and sources"),action:#selector(licenses),keyEquivalent:"")
        app.addItem(.separator())
        app.addItem(withTitle:L("从旧数据文件夹导入…","Import an old data folder…"),action:#selector(importMenu),keyEquivalent:"i")
        lanItem=app.addItem(withTitle:L("允许局域网访问","Allow local network access"),action:#selector(toggleLAN),keyEquivalent:"")
        app.addItem(withTitle:L("查看局域网地址与口令","Local network address and key"),action:#selector(networkInfo),keyEquivalent:"")
        app.addItem(withTitle:L("打开日志文件夹","Open logs folder"),action:#selector(openLogs),keyEquivalent:"")
        app.addItem(.separator())
        app.addItem(withTitle:L("退出 VoxStage","Quit VoxStage"),action:#selector(NSApplication.terminate(_:)),keyEquivalent:"q")
        let editItem=NSMenuItem();menu.addItem(editItem)
        let edit=NSMenu(title:L("编辑","Edit"));editItem.submenu=edit
        for (title,action,key) in [(L("撤销","Undo"),"undo:","z"),(L("剪切","Cut"),"cut:","x"),(L("复制","Copy"),"copy:","c"),(L("粘贴","Paste"),"paste:","v"),(L("全选","Select All"),"selectAll:","a")] {
            edit.addItem(withTitle:title,action:Selector(action),keyEquivalent:key)
        }
        NSApp.mainMenu=menu
    }
    func start() {
        ready=false
        do { try runtime.start(lan:lan) }
        catch { alert(error.localizedDescription);return }
        deadline=Date().addingTimeInterval(90)
        timer=Timer.scheduledTimer(withTimeInterval:0.1,repeats:true) { [weak self] _ in
            guard let self=self else { return }
            do {
                if try self.runtime.state() != nil {
                    self.timer?.invalidate();self.ready=true
                    self.web.load(URLRequest(url:URL(string:"http://127.0.0.1:\(self.runtime.port)/")!))
                } else if Date()>self.deadline {
                    self.timer?.invalidate();self.runtime.stop();self.alert(L("启动超时，请查看日志。","Startup timed out. See the logs."))
                }
            } catch { self.timer?.invalidate();self.runtime.stop();self.alert(error.localizedDescription) }
        }
    }
    func alert(_ text:String) {
        let alert=NSAlert();alert.messageText="VoxStage";alert.informativeText=text;alert.runModal()
    }
    @objc func about() {
        let version=Bundle.main.object(forInfoDictionaryKey:"CFBundleShortVersionString") as? String ?? ""
        alert("VoxStage \(version)\n"+L("源码：AGPL-3.0\nhttps://github.com/hera2019/VoxStage\n使用 FFmpeg（LGPL）、LAME、llama.cpp、whisper.cpp 和 Python；许可与对应源码随应用附带。","Source: AGPL-3.0\nhttps://github.com/hera2019/VoxStage\nUses FFmpeg (LGPL), LAME, llama.cpp, whisper.cpp and Python. Licenses and corresponding sources are included."))
    }
    @objc func licenses() { NSWorkspace.shared.open(runtime.resources.appendingPathComponent("licenses")) }
    @objc func openLogs() { NSWorkspace.shared.open(runtime.logs) }
    @objc func importMenu() {
        guard ready else { return }
        web.evaluateJavaScript("window.dispatchEvent(new CustomEvent('voxstage-request-import'))")
    }
    @objc func networkInfo() {
        guard lan,ready else { alert(L("先开启局域网访问。","Enable local network access first."));return }
        DispatchQueue.global().async {
            do { let value=try self.runtime.request("/desktop/network")
                let lines=value["urls"] as? [String] ?? []
                let key=value["key"] as? String ?? ""
                DispatchQueue.main.async { self.alert(lines.joined(separator:"\n")+"\n"+L("访问口令：","Access key: ")+key) }
            } catch { DispatchQueue.main.async { self.alert(error.localizedDescription) } }
        }
    }
    @objc func toggleLAN() {
        guard ready else { return }
        web.evaluateJavaScript("window.dispatchEvent(new CustomEvent('voxstage-request-network-toggle'))")
    }
    func toggleLANNow() {
        guard ready else { return }
        DispatchQueue.global().async {
            do {
                let tasks=try self.runtime.request("/model-tasks")
                let downloads=try self.runtime.request("/models")
                if !(tasks["tasks"] as? [[String:Any]] ?? []).isEmpty || downloads["active"] as? Bool == true {
                    DispatchQueue.main.async { self.alert(L("请等待本机任务结束后再切换局域网访问。","Wait for local tasks to finish before changing network access.")) };return
                }
                self.runtime.stop()
                DispatchQueue.main.async {
                    self.lan.toggle();self.lanItem.state=self.lan ? .on:.off;self.start()
                }
            } catch { DispatchQueue.main.async { self.alert(error.localizedDescription) } }
        }
    }
    func userContentController(_ controller:WKUserContentController,didReceive message:WKScriptMessage) {
        guard ready,message.frameInfo.isMainFrame,
              message.frameInfo.securityOrigin.host=="127.0.0.1",
              message.frameInfo.securityOrigin.port==runtime.port,
              let body=message.body as? [String:String],let action=body["action"] else { return }
        if action=="toggleLAN" { toggleLANNow();return }
        guard action=="chooseImportFolder" else { return }
        let panel=NSOpenPanel();panel.canChooseDirectories=true;panel.canChooseFiles=false
        panel.canCreateDirectories=false;panel.allowsMultipleSelection=false
        panel.message=L("选择开发版的 user-data 文件夹；确认导入前不会修改工程。","Choose the development user-data folder. Projects change only after confirmation.")
        panel.beginSheetModal(for:window) { response in
            guard response == .OK,let url=panel.url else { return }
            DispatchQueue.global().async {
                let value:[String:Any]
                do { value=try self.runtime.request("/legacy-import/preview",body:["folder":url.path]) }
                catch { value=["error":error.localizedDescription] }
                DispatchQueue.main.async {
                    if let bytes=try? JSONSerialization.data(withJSONObject:value),let json=String(data:bytes,encoding:.utf8) {
                        self.web.evaluateJavaScript("window.dispatchEvent(new CustomEvent('voxstage-import-preview',{detail:"+json+"}))")
                    }
                }
            }
        }
    }
    func webView(_ webView:WKWebView,decidePolicyFor action:WKNavigationAction,decisionHandler:@escaping (WKNavigationActionPolicy)->Void) {
        if action.shouldPerformDownload,let url=action.request.url,url.host=="127.0.0.1",url.port==runtime.port { decisionHandler(.download);return }
        if !ready,action.request.url?.absoluteString=="about:blank" { decisionHandler(.allow);return }
        if let url=action.request.url,url.scheme=="http",url.host=="127.0.0.1",url.port==runtime.port { decisionHandler(.allow);return }
        if action.navigationType == .linkActivated,let url=action.request.url,["https","http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        decisionHandler(.cancel)
    }
    func webView(_ webView:WKWebView,createWebViewWith configuration:WKWebViewConfiguration,for action:WKNavigationAction,windowFeatures:WKWindowFeatures)->WKWebView? {
        if action.navigationType == .linkActivated,let url=action.request.url,url.scheme=="https" { NSWorkspace.shared.open(url) }
        return nil
    }
    func localFrame(_ frame:WKFrameInfo)->Bool {
        return ready && frame.securityOrigin.host=="127.0.0.1" && frame.securityOrigin.port==runtime.port
    }
    func webView(_ webView:WKWebView,runOpenPanelWith parameters:WKOpenPanelParameters,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping ([URL]?)->Void) {
        guard localFrame(frame) else { completionHandler(nil);return }
        let panel=NSOpenPanel();panel.canChooseFiles=true;panel.canChooseDirectories=false
        panel.allowsMultipleSelection=parameters.allowsMultipleSelection
        panel.beginSheetModal(for:window) { answer in completionHandler(answer == .OK ? panel.urls:nil) }
    }
    func webView(_ webView:WKWebView,runJavaScriptAlertPanelWithMessage message:String,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping ()->Void) {
        guard localFrame(frame) else { completionHandler();return }
        let panel=NSAlert();panel.messageText="VoxStage";panel.informativeText=message
        panel.beginSheetModal(for:window) { _ in completionHandler() }
    }
    func webView(_ webView:WKWebView,runJavaScriptConfirmPanelWithMessage message:String,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping (Bool)->Void) {
        guard localFrame(frame) else { completionHandler(false);return }
        let panel=NSAlert();panel.messageText="VoxStage";panel.informativeText=message
        panel.addButton(withTitle:L("确认","Confirm"));panel.addButton(withTitle:L("取消","Cancel"))
        panel.beginSheetModal(for:window) { answer in completionHandler(answer == .alertFirstButtonReturn) }
    }
    func webView(_ webView:WKWebView,runJavaScriptTextInputPanelWithPrompt prompt:String,defaultText:String?,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping (String?)->Void) {
        guard localFrame(frame) else { completionHandler(nil);return }
        let panel=NSAlert();panel.messageText="VoxStage";panel.informativeText=prompt
        panel.addButton(withTitle:L("确认","Confirm"));panel.addButton(withTitle:L("取消","Cancel"))
        let field=NSTextField(frame:NSRect(x:0,y:0,width:320,height:26));field.stringValue=defaultText ?? ""
        panel.accessoryView=field
        panel.beginSheetModal(for:window) { answer in completionHandler(answer == .alertFirstButtonReturn ? field.stringValue:nil) }
        panel.window.makeFirstResponder(field)
    }
    func webView(_ webView:WKWebView,decidePolicyFor response:WKNavigationResponse,decisionHandler:@escaping (WKNavigationResponsePolicy)->Void) {
        guard let url=response.response.url,url.host=="127.0.0.1",url.port==runtime.port else { decisionHandler(.cancel);return }
        let attachment=(response.response as? HTTPURLResponse)?.value(forHTTPHeaderField:"Content-Disposition")?.lowercased().contains("attachment") ?? false
        decisionHandler(attachment || !response.canShowMIMEType ? .download:.allow)
    }
    func webView(_ webView:WKWebView,navigationAction:WKNavigationAction,didBecome download:WKDownload) { download.delegate=self }
    func webView(_ webView:WKWebView,navigationResponse:WKNavigationResponse,didBecome download:WKDownload) { download.delegate=self }
    func download(_ download:WKDownload,decideDestinationUsing response:URLResponse,suggestedFilename:String,completionHandler:@escaping (URL?)->Void) {
        let panel=NSSavePanel();panel.nameFieldStringValue=suggestedFilename
        panel.beginSheetModal(for:window) { result in completionHandler(result == .OK ? panel.url:nil) }
    }
    func download(_ download:WKDownload,didFailWithError error:Error,resumeData:Data?) { alert(L("文件下载未完成：","File download incomplete: ")+error.localizedDescription) }
    func applicationShouldHandleReopen(_ sender:NSApplication,hasVisibleWindows flag:Bool)->Bool { window.makeKeyAndOrderFront(nil);return true }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool { true }
    func applicationShouldTerminate(_ sender:NSApplication)->NSApplication.TerminateReply {
        timer?.invalidate();ready=false
        DispatchQueue.global().async { self.runtime.stop();DispatchQueue.main.async { sender.reply(toApplicationShouldTerminate:true) } }
        return .terminateLater
    }
    func applicationSupportsSecureRestorableState(_ app:NSApplication)->Bool { true }
}

if CommandLine.arguments.contains("--self-test") {
    // CLI verification creates no window and does not inspect any App/browser UI.
    let runtime=RuntimeController();let started=Date();var output:[String:Any]=[:];var status:Int32=0
    do {
        try runtime.start()
        let deadline=Date().addingTimeInterval(90)
        while try runtime.state()==nil {
            if Date()>deadline { throw RuntimeError.failed("Service startup timed out") };usleep(100_000)
        }
        let health=try runtime.request("/health")
        let models=try runtime.request("/models")
        output=["app":"VoxStage","port":runtime.port,"service_pid":Int(runtime.process!.processIdentifier),"health":health,
                "model_count":(models["models"] as? [Any])?.count ?? 0,
                "startup_seconds":Date().timeIntervalSince(started),"window_opened":false,"group_owned":runtime.ownsGroup,
                "offline":ProcessInfo.processInfo.environment["HF_HUB_OFFLINE"] ?? "child-only"]
        if CommandLine.arguments.contains("--self-test-wait") {
            let bytes=try JSONSerialization.data(withJSONObject:output,options:[.sortedKeys])
            print(String(data:bytes,encoding:.utf8)!);fflush(stdout)
            // A CLI test controls this wait; no window or browser is created.
            _=readLine()
        }
    } catch { output=["error":error.localizedDescription];status=1 }
    runtime.stop();output["service_stopped"]=true
    if let bytes=try? JSONSerialization.data(withJSONObject:output,options:[.sortedKeys]),let text=String(data:bytes,encoding:.utf8) { print(text) }
    exit(status)
} else {
    let application=NSApplication.shared
    let delegate=AppDelegate();application.delegate=delegate
    application.setActivationPolicy(.regular)
    application.run()
}
