# MapLibre creates these implementations from Dart through JNI dynamic proxies.
# R8 cannot see those implementations. Without these rules it rewrites the
# factory's return value to null in release APKs (debug and web still work).
-keep class com.github.josxha.maplibre.** { *; }
-keep interface io.flutter.plugin.platform.PlatformView { *; }
