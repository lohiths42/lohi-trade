package com.lohitrade.data.cache

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

/**
 * Room database for offline portfolio cache (Req 14.1).
 *
 * Single table key-value store with JSON blobs. WAL journal mode
 * is enabled by default in Room for better concurrent read performance.
 */
@Database(entities = [CacheEntry::class], version = 1, exportSchema = false)
abstract class OfflineCacheDatabase : RoomDatabase() {
    abstract fun cacheDao(): CacheDao

    companion object {
        @Volatile
        private var INSTANCE: OfflineCacheDatabase? = null

        fun getInstance(context: Context): OfflineCacheDatabase {
            return INSTANCE ?: synchronized(this) {
                INSTANCE ?: Room.databaseBuilder(
                    context.applicationContext,
                    OfflineCacheDatabase::class.java,
                    "offline_cache.db"
                ).build().also { INSTANCE = it }
            }
        }
    }
}
