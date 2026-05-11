package com.lohitrade.data.cache

import androidx.room.*

/**
 * Room entity for generic key-value cache with timestamps (Req 14.1).
 *
 * Stores serialized JSON blobs for positions, dashboard summary,
 * watchlists, orders, and signals — each keyed by data type.
 */
@Entity(tableName = "cache_entries")
data class CacheEntry(
    @PrimaryKey
    @ColumnInfo(name = "cache_key")
    val key: String,

    @ColumnInfo(name = "data", typeAffinity = ColumnInfo.BLOB)
    val data: ByteArray,

    @ColumnInfo(name = "updated_at")
    val updatedAt: Long // epoch millis
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is CacheEntry) return false
        return key == other.key && data.contentEquals(other.data) && updatedAt == other.updatedAt
    }

    override fun hashCode(): Int {
        var result = key.hashCode()
        result = 31 * result + data.contentHashCode()
        result = 31 * result + updatedAt.hashCode()
        return result
    }
}

@Dao
interface CacheDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entry: CacheEntry)

    @Query("SELECT * FROM cache_entries WHERE cache_key = :key LIMIT 1")
    suspend fun get(key: String): CacheEntry?

    @Query("DELETE FROM cache_entries")
    suspend fun deleteAll()

    @Query("SELECT updated_at FROM cache_entries WHERE cache_key = :key LIMIT 1")
    suspend fun getTimestamp(key: String): Long?
}
