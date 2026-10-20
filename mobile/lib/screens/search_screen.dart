import 'package:flutter/material.dart';
import '../models/models.dart';
import '../services/api_service.dart';

/// 🔍 跨站影视搜索页面
class SearchScreen extends StatefulWidget {
  final ApiService api;
  const SearchScreen({super.key, required this.api});

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  final TextEditingController _controller = TextEditingController();
  List<SearchResultItem> _results = [];
  bool _searching = false;

  Future<void> _doSearch() async {
    final kw = _controller.text.trim();
    if (kw.isEmpty) return;

    FocusScope.of(context).unfocus();
    setState(() => _searching = true);
    try {
      final list = await widget.api.search(kw);
      setState(() => _results = list);
      if (list.isEmpty && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('未检索到相关资源')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('搜索失败: $e')));
      }
    } finally {
      setState(() => _searching = false);
    }
  }

  void _showMagnets(SearchResultItem item) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) {
        return DraggableScrollableSheet(
          initialChildSize: 0.65,
          maxChildSize: 0.9,
          minChildSize: 0.4,
          builder: (_, controller) {
            return Container(
              decoration: const BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
              ),
              child: FutureBuilder<List<MagnetItem>>(
                future: widget.api.fetchDetail(item.detailUrl, item.siteKey),
                builder: (context, snapshot) {
                  if (snapshot.connectionState == ConnectionState.waiting) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snapshot.hasError) {
                    return Center(child: Text('抓取磁力失败: ${snapshot.error}'));
                  }
                  final magnets = snapshot.data ?? [];
                  return Column(
                    children: [
                      Padding(
                        padding: const EdgeInsets.all(16),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text(
                                item.title,
                                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.pop(ctx)),
                          ],
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                        child: Row(
                          children: [
                            ElevatedButton.icon(
                              onPressed: () async {
                                final ok = await widget.api.addSubscription(item.title, item.detailUrl, item.siteKey);
                                if (context.mounted) {
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(content: Text(ok ? '已成功加入追剧订阅！' : '加入订阅失败')),
                                  );
                                }
                              },
                              icon: const Icon(Icons.bookmark_add, size: 16),
                              label: const Text('订阅此剧'),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: Colors.indigo,
                                foregroundColor: Colors.white,
                                visualDensity: VisualDensity.compact,
                              ),
                            ),
                          ],
                        ),
                      ),
                      const Divider(height: 1),
                      Expanded(
                        child: magnets.isEmpty
                            ? const Center(child: Text('暂未解析出磁力链接'))
                            : ListView.separated(
                                controller: controller,
                                itemCount: magnets.length,
                                separatorBuilder: (_, __) => const Divider(height: 1),
                                itemBuilder: (context, idx) {
                                  final m = magnets[idx];
                                  return ListTile(
                                    dense: true,
                                    title: Text(m.label, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500)),
                                    subtitle: Text(m.quality.isNotEmpty ? m.quality : '分集磁力', style: const TextStyle(fontSize: 11)),
                                    trailing: IconButton(
                                      icon: const Icon(Icons.cloud_upload_outlined, color: Colors.indigo),
                                      onPressed: () async {
                                        final ok = await widget.api.sendDownload(m.url, epLabel: m.label, quality: m.quality);
                                        if (context.mounted) {
                                          ScaffoldMessenger.of(context).showSnackBar(
                                            SnackBar(content: Text(ok ? '已推送至下载器！' : '推送失败')),
                                          );
                                        }
                                      },
                                    ),
                                  );
                                },
                              ),
                      ),
                    ],
                  );
                },
              ),
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('跨站影视搜索', style: TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.indigo,
        foregroundColor: Colors.white,
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              controller: _controller,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _doSearch(),
              decoration: InputDecoration(
                hintText: '输入影视名称（如 繁花 / 人生复本 / 狂飙）',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: IconButton(
                  icon: const Icon(Icons.clear),
                  onPressed: () => _controller.clear(),
                ),
                contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
          ),
          Expanded(
            child: _searching
                ? const Center(child: CircularProgressIndicator())
                : ListView.separated(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    itemCount: _results.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, idx) {
                      final item = _results[idx];
                      return ListTile(
                        onTap: () => _showMagnets(item),
                        title: Text(item.title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                        subtitle: Row(
                          children: [
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                              decoration: BoxDecoration(
                                color: Colors.grey.shade200,
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(item.siteName, style: const TextStyle(fontSize: 10, color: Colors.black87)),
                            ),
                            const SizedBox(width: 8),
                            Text(item.date, style: TextStyle(fontSize: 11, color: Colors.grey.shade500)),
                          ],
                        ),
                        trailing: const Icon(Icons.chevron_right, size: 20, color: Colors.grey),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
