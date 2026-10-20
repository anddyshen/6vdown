/// 6vdown 移动端核心数据模型

class SubscriptionItem {
  final int id;
  final String title;
  final String detailUrl;
  final String siteKey;
  final int? embySeriesId;
  final int isActive;
  final String? lastChecked;
  final String? latestResourceTitle;
  bool isChecking;

  SubscriptionItem({
    required this.id,
    required this.title,
    required this.detailUrl,
    this.siteKey = '',
    this.embySeriesId,
    this.isActive = 1,
    this.lastChecked,
    this.latestResourceTitle,
    this.isChecking = false,
  });

  factory SubscriptionItem.fromJson(Map<String, dynamic> json) {
    return SubscriptionItem(
      id: json['id'] ?? 0,
      title: json['title'] ?? '',
      detailUrl: json['detail_url'] ?? '',
      siteKey: json['site_key'] ?? '',
      embySeriesId: json['emby_series_id'],
      isActive: json['is_active'] ?? 1,
      lastChecked: json['last_checked'],
      latestResourceTitle: json['latest_resource_title'],
    );
  }
}

class MagnetItem {
  final String label;
  final String url;
  final String size;
  final String quality;

  MagnetItem({
    required this.label,
    required this.url,
    this.size = '',
    this.quality = '',
  });

  factory MagnetItem.fromJson(Map<String, dynamic> json) {
    return MagnetItem(
      label: json['label'] ?? '',
      url: json['url'] ?? '',
      size: json['size'] ?? '',
      quality: json['quality'] ?? '',
    );
  }
}

class WorkbenchItem {
  final String title;
  final String date;
  final String desc;
  final String detailUrl;
  final String block;
  final int magnetsCount;
  final String siteName;
  final String siteKey;
  final List<MagnetItem> magnets;

  WorkbenchItem({
    required this.title,
    required this.date,
    required this.desc,
    required this.detailUrl,
    required this.block,
    required this.magnetsCount,
    this.siteName = '',
    this.siteKey = '',
    this.magnets = const [],
  });

  factory WorkbenchItem.fromJson(Map<String, dynamic> json) {
    var rawMagnets = json['magnets'] as List? ?? [];
    return WorkbenchItem(
      title: json['title'] ?? '',
      date: json['date'] ?? '',
      desc: json['desc'] ?? '',
      detailUrl: json['detail_url'] ?? '',
      block: json['block'] ?? '',
      magnetsCount: json['magnets_count'] ?? 0,
      siteName: json['site_name'] ?? '',
      siteKey: json['site_key'] ?? json['module_id'] ?? '',
      magnets: rawMagnets.map((m) => MagnetItem.fromJson(m)).toList(),
    );
  }
}

class SearchResultItem {
  final String title;
  final String detailUrl;
  final String date;
  final String siteName;
  final String siteKey;

  SearchResultItem({
    required this.title,
    required this.detailUrl,
    required this.date,
    required this.siteName,
    required this.siteKey,
  });

  factory SearchResultItem.fromJson(Map<String, dynamic> json) {
    return SearchResultItem(
      title: json['title'] ?? '',
      detailUrl: json['detail_url'] ?? '',
      date: json['date'] ?? '',
      siteName: json['site_name'] ?? '',
      siteKey: json['site_key'] ?? '',
    );
  }
}

class DownloadHostItem {
  final int id;
  final String type;
  final String name;
  final String address;
  final int port;
  final String username;
  final bool isActive;
  final bool hasPassword;

  DownloadHostItem({
    required this.id,
    required this.type,
    required this.name,
    required this.address,
    required this.port,
    required this.username,
    required this.isActive,
    required this.hasPassword,
  });

  factory DownloadHostItem.fromJson(Map<String, dynamic> json) {
    return DownloadHostItem(
      id: json['id'] ?? 0,
      type: json['type'] ?? 'qb',
      name: json['name'] ?? '',
      address: json['address'] ?? '',
      port: json['port'] ?? 8080,
      username: json['username'] ?? '',
      isActive: (json['is_active'] == 1 || json['is_active'] == true),
      hasPassword: json['has_password'] ?? false,
    );
  }
}
