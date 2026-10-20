import 'package:flutter/material.dart';
import '../models/models.dart';
import '../services/api_service.dart';

/// ⚡ 资源解析工作台
class WorkbenchScreen extends StatefulWidget {
  final ApiService api;
  const WorkbenchScreen({super.key, required this.api});

  @override
  State<WorkbenchScreen> createState() => _WorkbenchScreenState();
}

class _WorkbenchScreenState extends State<WorkbenchScreen> {
  List<WorkbenchItem> _items = [];
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() => _loading = true);
    try {
      final list = await widget.api.getWorkbench();
      setState(() => _items = list);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('获取工作台数据失败: $e')));
      }
    } finally {
      setState(() => _loading = false);
    }
  }

  void _showMagnets(WorkbenchItem item) {
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
                future: item.magnets.isNotEmpty
                    ? Future.value(item.magnets)
                    : widget.api.fetchDetail(item.detailUrl, item.siteKey),
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
                        child: ListView.separated(
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
        title: const Text('资源解析工作台', style: TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.indigo,
        foregroundColor: Colors.white,
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : ListView.builder(
                padding: const EdgeInsets.all(12),
                itemCount: _items.length,
                itemBuilder: (context, idx) {
                  final it = _items[idx];
                  return Card(
                    margin: const EdgeInsets.only(bottom: 10),
                    elevation: 1,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(12),
                      onTap: () => _showMagnets(it),
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                if (it.block.isNotEmpty)
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                    margin: const EdgeInsets.only(right: 6),
                                    decoration: BoxDecoration(
                                      color: Colors.indigo.shade50,
                                      borderRadius: BorderRadius.circular(4),
                                    ),
                                    child: Text(it.block, style: TextStyle(fontSize: 10, color: Colors.indigo.shade700, fontWeight: FontWeight.bold)),
                                  ),
                                Expanded(
                                  child: Text(
                                    it.title,
                                    style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                              ],
                            ),
                            if (it.desc.isNotEmpty) ...[
                              const SizedBox(height: 4),
                              Text(
                                it.desc,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
                              ),
                            ],
                            const SizedBox(height: 8),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Text(it.date, style: TextStyle(fontSize: 11, color: Colors.grey.shade500)),
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                  decoration: BoxDecoration(
                                    color: it.magnetsCount > 0 ? Colors.emerald.shade50 : Colors.grey.shade100,
                                    borderRadius: BorderRadius.circular(10),
                                  ),
                                  child: Text(
                                    it.magnetsCount > 0 ? '磁力 ${it.magnetsCount} 条' : '待抓取',
                                    style: TextStyle(
                                      fontSize: 11,
                                      color: it.magnetsCount > 0 ? Colors.emerald.shade700 : Colors.grey.shade600,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  );
                },
              ),
      ),
    );
  }
}
