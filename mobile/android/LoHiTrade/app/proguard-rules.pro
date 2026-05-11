# LoHi-TRADE ProGuard rules

# Retrofit
-keepattributes Signature
-keepattributes *Annotation*
-keep class retrofit2.** { *; }
-keepclasseswithmembers class * {
    @retrofit2.http.* <methods>;
}

# Gson
-keep class com.lohitrade.data.models.** { *; }
-keepclassmembers class com.lohitrade.data.models.** { *; }

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**

# Firebase
-keep class com.google.firebase.** { *; }
