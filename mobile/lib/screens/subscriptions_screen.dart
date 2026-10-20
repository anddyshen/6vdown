import 'package:flutter/material.dart';
import '../models/models.dart';
import '../services/api_service.dart';

/// 📺 追剧订阅管理页面
class SubscriptionsScreen extends StatefulWidget {
  final ApiService api;
  const SubscriptionsScreen({super.key, required this.api});

  @override
  State<SubscriptionsScreen> createState() => _SubscriptionsScreenState();
}

class _SubscriptionsScreenState extends State<SubscriptionsScreen> {
  List<SubscriptionItem> _subs = [];
  bool _loading = false;
  bool _checkingAll = false;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() => _loading = true);
    try {
      final list = await widget.api.getSubscriptions();
      setState(() => _subs = list);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('获取订阅失败: $e')));
      }
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _checkSingle(SubscriptionItem sub) async {
    setState(() => sub.isChecking = true);
    try {
      final res = await widget.api.checkSubscription(sub.id);
      final update = res['update'];
      if (mounted) {
        if (update != null) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('《${sub.title}》发现新更新！')),
          );
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('《${sub.title}》已是最新进度')),
          );
        }
      }
      _refresh();
    } finally {
      setState(() => sub.isChecking = false);
    }
  }

  Future<void> _checkAll() async {
    setState(() => _checkingAll = true);
    try {
      final res = await widget.api.checkAllSubscriptions();
      final updates = res['updates'] as List? ?? [];
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('巡检完毕！共发现 ${updates.length} 部剧集有新更新')),
        );
      }
      _refresh();
    } finally {
      setState(() => _checkingAll = false);
    }
  }

  void _showDetailMagnets(SubscriptionItem sub) async {
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
                future: widget.api.fetchDetail(sub.detailUrl, sub.siteKey),
                builder: (context, snapshot) {
                  if (snapshot.connectionState == ConnectionState.waiting) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snapshot.hasError) {
                    return Center(child: Text('加载分集失败: ${snapshot.error}'));
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
                                sub.title,
                                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.pop(ctx)),
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
                                  final ok = await widget.api.sendDownload(m.url, subId: sub.id, epLabel: m.label, quality: m.quality);
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
        title: const Text('我的追剧订阅', style: TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.indigo,
        foregroundColor: Colors.white,
        actions: [
          IconButton(
            icon: _checkingAll
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.sync),
            tooltip: '巡检全部剧集',
            onPressed: _checkingAll ? null : _checkAll,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _subs.isEmpty
                ? const Center(
                    child: Text('暂无追剧订阅，请在工作台或搜索页添加', style: TextStyle(color: Colors.grey)),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.all(12),
                    itemCount: _subs.length,
                    itemBuilder: (context, idx) {
                      final sub = _subs[idx];
                      return Card(
                        margin: const EdgeInsets.only(bottom: 10),
                        elevation: 1,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                        child: InkWell(
                          borderRadius: BorderRadius.circular(12),
                          onTap: () => _showDetailMagnets(sub),
                          child: Padding(
                            padding: const EdgeInsets.all(14),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Expanded(
                                      child: Text(
                                        sub.title,
                                        style: const TextStyle(fontSize: 15, fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                    if (sub.siteKey.isNotEmpty)
                                      Container(
                                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                        decoration: BoxDecoration(
                                          color: Colors.indigo.shade50,
                                          borderRadius: BorderRadius.circular(6),
                                        ),
                                        child: Text(
                                          sub.siteKey.toUpperCase(),
                                          style: TextStyle(fontSize: 10, color: Colors.indigo.shade700, fontWeight: FontWeight.bold),
                                        ),
                                      ),
                                  ],
                                ),
                                const SizedBox(height: 6),
                                Text(
                                  sub.latestResourceTitle ?? '已是最新收录状态',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
                                ),
                                const SizedBox(height: 10),
                                Row(
                                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                  children: [
                                    Text(
                                      '检查时间: ${sub.lastChecked ?? '未记录'}',
                                      style: TextStyle(fontSize: 11, color: Colors.grey.shade500),
                                    ),
                                    Row(
                                      children: [
                                        TextButton.icon(
                                          onPressed: sub.isChecking ? null : () => _checkSingle(sub),
                                          icon: sub.isChecking
                                              ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                                              : const Icon(Icons.refresh, size: 16),
                                          label: const Text('检查', style: TextStyle(fontSize: 12)),
                                        ),
                                        TextButton.icon(
                                          onPressed: () => _showDetailMagnets(sub),
                                          icon: const Icon(Icons.list_alt, size: 16),
                                          label: const Text('分集', style: TextStyle(fontSize: 12)),
                                        ),
                                      ],
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
