import 'package:flutter/material.dart';
import '../models/models.dart';
import '../services/api_service.dart';
import '../services/storage_service.dart';

/// ⚙️ 设置与主机管理页面
class SettingsScreen extends StatefulWidget {
  final ApiService api;
  final StorageService storage;
  const SettingsScreen({super.key, required this.api, required this.storage});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _lanController = TextEditingController();
  final _wanController = TextEditingController();
  final _tokenController = TextEditingController();

  List<DownloadHostItem> _hosts = [];
  bool _testingConn = false;
  String _connStatus = '';
  bool _connOk = false;

  @override
  void initState() {
    super.initState();
    _lanController.text = widget.storage.lanUrl;
    _wanController.text = widget.storage.wanUrl;
    widget.storage.getApiToken().then((tok) {
      if (mounted) _tokenController.text = tok;
    });
    _loadHosts();
  }

  Future<void> _loadHosts() async {
    try {
      final hosts = await widget.api.getHosts();
      setState(() => _hosts = hosts);
    } catch (_) {}
  }

  Future<void> _saveSettings() async {
    await widget.storage.setLanUrl(_lanController.text.trim());
    await widget.storage.setWanUrl(_wanController.text.trim());
    await widget.storage.setApiToken(_tokenController.text.trim());
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('配置已保存！')));
    }
  }

  Future<void> _testConnection() async {
    await _saveSettings();
    setState(() {
      _testingConn = true;
      _connStatus = '正在探测节点连通性...';
    });
    final ok = await widget.api.autoDetectAndConnect();
    setState(() {
      _testingConn = false;
      _connOk = ok;
      _connStatus = ok
          ? '连接成功！当前生效节点: ${widget.api.activeBaseUrl}'
          : '连接失败，请检查内网/公网地址或 API Token 是否正确';
    });
    if (ok) _loadHosts();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('服务器与下载器设置', style: TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.indigo,
        foregroundColor: Colors.white,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // 1. 网络与节点配置
          Card(
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.router, color: Colors.indigo, size: 20),
                      SizedBox(width: 8),
                      Text('NAS Docker 服务端地址', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                    ],
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _lanController,
                    decoration: const InputDecoration(
                      labelText: '局域网地址 (内网优先)',
                      hintText: 'http://192.168.1.3:5080',
                      border: OutlineInputBorder(),
                      dense: true,
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _wanController,
                    decoration: const InputDecoration(
                      labelText: '公网 / DDNS 域名地址 (外网备用)',
                      hintText: 'http://nas.yourdomain.com:53880',
                      border: OutlineInputBorder(),
                      dense: true,
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _tokenController,
                    obscureText: true,
                    decoration: const InputDecoration(
                      labelText: '安全访问令牌 (API Token)',
                      hintText: '公网暴露时必填，留空为免密',
                      border: OutlineInputBorder(),
                      dense: true,
                    ),
                  ),
                  const SizedBox(height: 14),
                  if (_connStatus.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Text(
                        _connStatus,
                        style: TextStyle(
                          fontSize: 12,
                          color: _connOk ? Colors.emerald.shade700 : Colors.red.shade700,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: _saveSettings,
                          child: const Text('保存配置'),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: ElevatedButton.icon(
                          onPressed: _testingConn ? null : _testConnection,
                          icon: _testingConn
                              ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                              : const Icon(Icons.bolt, size: 16),
                          label: const Text('测试连接'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.indigo,
                            foregroundColor: Colors.white,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),

          // 2. 家中下载器状态卡片
          Card(
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.download, color: Colors.indigo, size: 20),
                      SizedBox(width: 8),
                      Text('家中下载器状态', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                    ],
                  ),
                  const SizedBox(height: 8),
                  if (_hosts.isEmpty)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: Text('暂未读取到下载器主机，请先测试连接服务端', style: TextStyle(color: Colors.grey, fontSize: 12)),
                    )
                  else
                    ..._hosts.map((h) {
                      return ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text('${h.name} (${h.type.toUpperCase()})', style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold)),
                        subtitle: Text('${h.address}:${h.port}', style: const TextStyle(fontSize: 12)),
                        trailing: h.isActive
                            ? Container(
                                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                decoration: BoxDecoration(
                                  color: Colors.emerald.shade50,
                                  borderRadius: BorderRadius.circular(6),
                                ),
                                child: Text('激活中', style: TextStyle(color: Colors.emerald.shade700, fontSize: 11, fontWeight: FontWeight.bold)),
                              )
                            : OutlinedButton(
                                onPressed: () async {
                                  await widget.api.activateHost(h.id);
                                  _loadHosts();
                                },
                                child: const Text('设为默认', style: TextStyle(fontSize: 11)),
                              ),
                      );
                    }),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
