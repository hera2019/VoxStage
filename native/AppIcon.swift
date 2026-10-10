// Draws the sidebar mark into a macOS .iconset: an italic serif v on the brand's
// deep green, same geometry as frontend/public/favicon.svg (64-unit grid).
// NSImage's SVG renderer drops font-style, so the mark is drawn here directly.
// Usage: swift AppIcon.swift <out.iconset>. Claude Hera, 2026-10-10.
import Cocoa

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write("usage: AppIcon.swift <out.iconset>\n".data(using: .utf8)!)
    exit(1)
}
let folder = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
let green = NSColor(srgbRed: 0x34/255.0, green: 0x4e/255.0, blue: 0x3d/255.0, alpha: 1)
let cream = NSColor(srgbRed: 0xe4/255.0, green: 0xea/255.0, blue: 0xc3/255.0, alpha: 1)

for points in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = points * scale
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                                      bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                      colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
        // macOS icon grid: the rounded square fills about 80% of the canvas.
        let side = CGFloat(pixels) * 0.8, origin = CGFloat(pixels) * 0.1, unit = side / 60
        green.setFill()
        NSBezierPath(roundedRect: NSRect(x: origin, y: origin, width: side, height: side),
                     xRadius: 16 * unit, yRadius: 16 * unit).fill()
        let font = NSFont(name: "Georgia-Italic", size: 50 * unit) ?? NSFont.systemFont(ofSize: 50 * unit)
        let text = NSAttributedString(string: "v", attributes: [.font: font, .foregroundColor: cream])
        // SVG: centred on x=31, baseline y=47 of a 64 grid whose square starts at 2.
        let width = text.size().width
        let baseline = origin + (62 - 47) * unit
        text.draw(at: NSPoint(x: origin + (31 - 2) * unit - width / 2, y: baseline + font.descender))
        NSGraphicsContext.restoreGraphicsState()
        let name = "icon_\(points)x\(points)" + (scale == 2 ? "@2x" : "") + ".png"
        try bitmap.representation(using: .png, properties: [:])!.write(to: folder.appendingPathComponent(name))
    }
}
