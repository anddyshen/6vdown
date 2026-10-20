import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'api_service.dart';

/// 移动端前台剪贴板磁力嗅探器（零常驻后台功耗，仅前台唤醒时感知）
class ClipboardService {
  static String _lastCheckedClipboard = '';

  static Future<void> checkOnResume(BuildContext context, ApiService api) async {
    try {
      final data = await Clipboard.getData(Clipboard.kTextPlain);
      final text = data?.text?.trim() ?? '';
      if (text.isEmpty || text == _lastCheckedClipboard) return;

      // 匹配磁力链接
      final magnetRegex = RegExp(r'magnet:\?xt=urn:btih:[a-zA-Z0-9]{32,40}', caseSensitive: false);
      final match = magnetRegex.firstMatch(text);

      if (match != null) {
        _lastCheckedClipboard = text;
        if (!context.mounted) return;
        _showMagnetSheet(context, text, api);
      }
    } catch (_) {
      // 剪贴板读取失败静默忽略
    }
  }

  static void _showMagnetSheet(BuildContext context, String magnetUrl, ApiService api) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (ctx) {
        bool sending = false;
        return StatefulBuilder(
          builder: (ctx, setState) {
            return Container(
              padding: const EdgeInsets.all(20),
              decoration: const BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
              ),
              child: SafeArea(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.all(8),
                          decoration: BoxDecoration(
                            color: Colors.indigo.shade50,
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: const Icon(Icons.link, color: Colors.indigo),
                        ),
                        const SizedBox(width: 12),
                        const Expanded(
                          child: Text(
                            '检测到剪贴板磁力链接',
                            style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.grey.shade100,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        magnetUrl,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 12, fontFamily: 'monospace', color: Colors.black87),
                      ),
                    ),
                    const SizedBox(height: 16),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        TextButton(
                          onPressed: () => Navigator.pop(ctx),
                          child: const Text('忽略'),
                        ),
                        const SizedBox(width: 8),
                        ElevatedButton.icon(
                          onPressed: sending
                              ? null
                              : () async {
                                  setState(() => sending = true);
                                  try {
                                    final ok = await api.sendDownload(magnetUrl);
                                    if (ctx.mounted) {
                                      Navigator.pop(ctx);
                                      ScaffoldMessenger.of(context).showSnackBar(
                                        SnackBar(
                                          content: Text(ok ? '已成功推送到 NAS 下载器！' : '推送下载失败，请检查下载器状态'),
                                          backgroundColor: ok ? Colors.emerald : Colors.red,
                                        ),
                                      );
                                    }
                                  } catch (e) {
                                    if (ctx.mounted) {
                                      Navigator.pop(ctx);
                                      ScaffoldMessenger.of(context).showSnackBar(
                                        SnackBar(content: Text('发送失败: $e'), backgroundColor: Colors.red),
                                      );
                                    }
                                  }
                                },
                          icon: sending
                              ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                              : const Icon(Icons.cloud_upload_outlined),
                          label: Text(sending ? '推送中...' : '推送到家中 NAS'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.indigo,
                            foregroundColor: Colors.white,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }
}
