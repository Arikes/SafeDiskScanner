import Foundation

// FileManager resolves volume-specific Trash locations and name collisions.
// JSON over stdin keeps file names (including quotes/newlines) out of shell code.
let input = FileHandle.standardInput.readDataToEndOfFile()
do {
    let paths = try JSONDecoder().decode([String].self, from: input)
    var results: [[String: Any]] = []
    for path in paths {
        let url = URL(fileURLWithPath: path).standardizedFileURL
        if !path.hasPrefix("/") || url.path == "/" {
            results.append(["path": path, "trashed": false, "error": "拒绝移动无效路径或磁盘根目录"])
            continue
        }
        do {
            var destination: NSURL?
            try FileManager.default.trashItem(at: url, resultingItemURL: &destination)
            results.append(["path": path, "trashed": true, "trashPath": destination?.path ?? ""])
        } catch {
            results.append(["path": path, "trashed": false, "error": error.localizedDescription])
        }
    }
    let output = try JSONSerialization.data(withJSONObject: results, options: [.sortedKeys])
    FileHandle.standardOutput.write(output)
} catch {
    FileHandle.standardError.write(Data(error.localizedDescription.utf8))
    exit(1)
}
