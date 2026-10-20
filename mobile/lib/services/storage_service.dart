import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 本地与安全加密存储服务
class StorageService {
  static const _keyLanUrl = 'c2down_lan_url';
  static const _keyWanUrl = 'c2down_wan_url';
  static const _keyApiToken = 'c2down_api_token';
  static const _keyCurrentUrl = 'c2down_current_url';

  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );

  SharedPreferences? _prefs;

  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
  }

  String get lanUrl => _prefs?.getString(_keyLanUrl) ?? 'http://192.168.1.3:5080';
  Future<void> setLanUrl(String val) async => await _prefs?.setString(_keyLanUrl, val.trim());

  String get wanUrl => _prefs?.getString(_keyWanUrl) ?? '';
  Future<void> setWanUrl(String val) async => await _prefs?.setString(_keyWanUrl, val.trim());

  String get currentActiveUrl => _prefs?.getString(_keyCurrentUrl) ?? lanUrl;
  Future<void> setCurrentActiveUrl(String val) async => await _prefs?.setString(_keyCurrentUrl, val.trim());

  Future<String> getApiToken() async {
    return await _secureStorage.read(key: _keyApiToken) ?? '';
  }

  Future<void> setApiToken(String token) async {
    await _secureStorage.write(key: _keyApiToken, value: token.trim());
  }
}
