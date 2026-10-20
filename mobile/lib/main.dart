import 'package:flutter/material.dart';
import 'screens/subscriptions_screen.dart';
import 'screens/search_screen.dart';
import 'screens/workbench_screen.dart';
import 'screens/settings_screen.dart';
import 'services/api_service.dart';
import 'services/clipboard_service.dart';
import 'services/storage_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final storage = StorageService();
  await storage.init();
  final api = ApiService(storage: storage);
  // 启动时静默探测内外网最佳节点
  api.autoDetectAndConnect();

  runApp(VdownApp(api: api, storage: storage));
}

class VdownApp extends StatelessWidget {
  final ApiService api;
  final StorageService storage;

  const VdownApp({super.key, required this.api, required this.storage});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '6vdown',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
      ),
      darkTheme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo, brightness: Brightness.dark),
      ),
      home: MainShell(api: api, storage: storage),
    );
  }
}

class MainShell extends StatefulWidget {
  final ApiService api;
  final StorageService storage;
  const MainShell({super.key, required this.api, required this.storage});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> with WidgetsBindingObserver {
  int _currentIndex = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // 首次进入检测剪贴板
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ClipboardService.checkOnResume(context, widget.api);
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 仅当前台唤醒应用时检查剪贴板，彻底杜绝后台常驻耗电
    if (state == AppLifecycleState.resumed) {
      ClipboardService.checkOnResume(context, widget.api);
    }
  }

  @override
  Widget build(BuildContext context) {
    final screens = [
      SubscriptionsScreen(api: widget.api),
      SearchScreen(api: widget.api),
      WorkbenchScreen(api: widget.api),
      SettingsScreen(api: widget.api, storage: widget.storage),
    ];

    return Scaffold(
      body: IndexedStack(
        index: _currentIndex,
        children: screens,
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (idx) => setState(() => _currentIndex = idx),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.tv), label: '追剧'),
          NavigationDestination(icon: Icon(Icons.search), label: '搜索'),
          NavigationDestination(icon: Icon(Icons.bolt), label: '工作台'),
          NavigationDestination(icon: Icon(Icons.settings), label: '设置'),
        ],
      ),
    );
  }
}
