import 'dart:async';
import 'package:dio/dio.dart';
import '../models/models.dart';
import 'storage_service.dart';

/// 移动端 API 客户端与内外网无缝切换网络层
class ApiService {
  final StorageService storage;
  late final Dio _dio;

  String activeBaseUrl = '';
  String activeToken = '';

  ApiService({required this.storage}) {
    _dio = Dio(BaseOptions(
      connectTimeout: const Duration(seconds: 8),
      receiveTimeout: const Duration(seconds: 15),
      headers: {'Content-Type': 'application/json'},
    ));

    // 自动注入 API Token 拦截器
    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) {
        if (activeToken.isNotEmpty) {
          options.headers['X-API-Token'] = activeToken;
        }
        return handler.next(options);
      },
      onError: (DioException error, handler) {
        return handler.next(error);
      },
    ));
  }

  /// 智能探测并连接最佳可用节点（优先探测内网，失败秒切公网）
  Future<bool> autoDetectAndConnect() async {
    activeToken = await storage.getApiToken();
    final lan = storage.lanUrl.trim();
    final wan = storage.wanUrl.trim();

    // 1. 优先探测局域网（超短 1.5 秒超时）
    if (lan.isNotEmpty) {
      final ok = await _probeUrl(lan, activeToken, const Duration(milliseconds: 1500));
      if (ok) {
        activeBaseUrl = lan;
        await storage.setCurrentActiveUrl(lan);
        return true;
      }
    }

    // 2. 局域网不可用，探测公网 DDNS 节点
    if (wan.isNotEmpty) {
      final ok = await _probeUrl(wan, activeToken, const Duration(seconds: 4));
      if (ok) {
        activeBaseUrl = wan;
        await storage.setCurrentActiveUrl(wan);
        return true;
      }
    }

    // 3. 降级使用上次记忆节点
    activeBaseUrl = storage.currentActiveUrl;
    return false;
  }

  /// 探测指定节点连通性与 Token 校验
  Future<bool> _probeUrl(String baseUrl, String token, Duration timeout) async {
    try {
      final probeDio = Dio(BaseOptions(
        connectTimeout: timeout,
        receiveTimeout: timeout,
      ));
      final res = await probeDio.post(
        '$baseUrl/api/auth/verify',
        data: {'token': token},
        options: Options(headers: {'X-API-Token': token}),
      );
      return res.statusCode == 200 && (res.data['ok'] == true);
    } catch (_) {
      return false;
    }
  }

  String _cleanUrl(String path) {
    var base = activeBaseUrl.endsWith('/')
        ? activeBaseUrl.substring(0, activeBaseUrl.length - 1)
        : activeBaseUrl;
    return '$base$path';
  }

  // ------------------------------------------------------------ 订阅接口
  Future<List<SubscriptionItem>> getSubscriptions() async {
    final res = await _dio.get(_cleanUrl('/api/subscriptions'));
    final list = res.data as List;
    return list.map((e) => SubscriptionItem.fromJson(e)).toList();
  }

  Future<Map<String, dynamic>> checkSubscription(int id) async {
    final res = await _dio.post(_cleanUrl('/api/subscriptions/$id/check'));
    return res.data;
  }

  Future<Map<String, dynamic>> checkAllSubscriptions() async {
    final res = await _dio.post(_cleanUrl('/api/subscriptions/check_all'));
    return res.data;
  }

  Future<bool> addSubscription(String title, String detailUrl, String siteKey) async {
    final res = await _dio.post(_cleanUrl('/api/subscriptions'), data: {
      'title': title,
      'detail_url': detailUrl,
      'site_key': siteKey,
    });
    return res.data['ok'] == true;
  }

  Future<bool> deleteSubscription(int id) async {
    final res = await _dio.delete(_cleanUrl('/api/subscriptions/$id'));
    return res.data['ok'] == true;
  }

  // ------------------------------------------------------------ 工作台接口
  Future<List<WorkbenchItem>> getWorkbench({List<int>? siteIds}) async {
    String query = siteIds != null && siteIds.isNotEmpty ? '?site_ids=${siteIds.join(",")}' : '';
    final res = await _dio.get(_cleanUrl('/api/workbench$query'));
    final list = res.data as List;
    return list.map((e) => WorkbenchItem.fromJson(e)).toList();
  }

  Future<List<MagnetItem>> fetchDetail(String detailUrl, String moduleId) async {
    final res = await _dio.post(_cleanUrl('/api/workbench/detail'), data: {
      'detail_url': detailUrl,
      'module_id': moduleId,
    });
    final raw = res.data['magnets'] as List? ?? [];
    return raw.map((m) => MagnetItem.fromJson(m)).toList();
  }

  // ------------------------------------------------------------ 搜索接口
  Future<List<SearchResultItem>> search(String keyword, {int maxPages = 1}) async {
    final res = await _dio.post(_cleanUrl('/api/search'), data: {
      'keyword': keyword,
      'max_pages': maxPages,
    });
    final raw = res.data['items'] as List? ?? [];
    return raw.map((i) => SearchResultItem.fromJson(i)).toList();
  }

  // ------------------------------------------------------------ 推送下载接口
  Future<bool> sendDownload(String url, {String epLabel = '', String quality = '', int? subId}) async {
    final res = await _dio.post(_cleanUrl('/api/download'), data: {
      'url': url,
      'ep_label': epLabel,
      'quality': quality,
      'sub_id': subId,
    });
    return res.data['ok'] == true;
  }

  // ------------------------------------------------------------ 主机设置接口
  Future<List<DownloadHostItem>> getHosts() async {
    final res = await _dio.get(_cleanUrl('/api/settings'));
    final raw = res.data['hosts'] as List? ?? [];
    return raw.map((h) => DownloadHostItem.fromJson(h)).toList();
  }

  Future<bool> activateHost(int hostId) async {
    final res = await _dio.post(_cleanUrl('/api/settings/host_activate'), data: {'id': hostId});
    return res.data['ok'] == true;
  }

  Future<Map<String, dynamic>> testHost(Map<String, dynamic> hostData) async {
    final res = await _dio.post(_cleanUrl('/api/settings/host_test'), data: hostData);
    return res.data;
  }
}
