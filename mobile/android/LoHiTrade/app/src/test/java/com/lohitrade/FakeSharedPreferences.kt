package com.lohitrade

import android.content.SharedPreferences

/**
 * In-memory SharedPreferences implementation for unit testing.
 * Avoids Android framework dependency.
 */
class FakeSharedPreferences : SharedPreferences {

    private val data = mutableMapOf<String, Any?>()
    private val listeners = mutableSetOf<SharedPreferences.OnSharedPreferenceChangeListener>()

    override fun getAll(): MutableMap<String, *> = data.toMutableMap()

    override fun getString(key: String?, defValue: String?): String? =
        data[key] as? String ?: defValue

    override fun getStringSet(key: String?, defValues: MutableSet<String>?): MutableSet<String>? =
        @Suppress("UNCHECKED_CAST")
        (data[key] as? MutableSet<String>) ?: defValues

    override fun getInt(key: String?, defValue: Int): Int =
        data[key] as? Int ?: defValue

    override fun getLong(key: String?, defValue: Long): Long =
        data[key] as? Long ?: defValue

    override fun getFloat(key: String?, defValue: Float): Float =
        data[key] as? Float ?: defValue

    override fun getBoolean(key: String?, defValue: Boolean): Boolean =
        data[key] as? Boolean ?: defValue

    override fun contains(key: String?): Boolean = data.containsKey(key)

    override fun edit(): SharedPreferences.Editor = FakeEditor()

    override fun registerOnSharedPreferenceChangeListener(
        listener: SharedPreferences.OnSharedPreferenceChangeListener?
    ) {
        listener?.let { listeners.add(it) }
    }

    override fun unregisterOnSharedPreferenceChangeListener(
        listener: SharedPreferences.OnSharedPreferenceChangeListener?
    ) {
        listener?.let { listeners.remove(it) }
    }

    fun clear() {
        data.clear()
    }

    private inner class FakeEditor : SharedPreferences.Editor {
        private val pending = mutableMapOf<String, Any?>()
        private var clearRequested = false

        override fun putString(key: String?, value: String?): SharedPreferences.Editor {
            key?.let { pending[it] = value }
            return this
        }

        override fun putStringSet(key: String?, values: MutableSet<String>?): SharedPreferences.Editor {
            key?.let { pending[it] = values }
            return this
        }

        override fun putInt(key: String?, value: Int): SharedPreferences.Editor {
            key?.let { pending[it] = value }
            return this
        }

        override fun putLong(key: String?, value: Long): SharedPreferences.Editor {
            key?.let { pending[it] = value }
            return this
        }

        override fun putFloat(key: String?, value: Float): SharedPreferences.Editor {
            key?.let { pending[it] = value }
            return this
        }

        override fun putBoolean(key: String?, value: Boolean): SharedPreferences.Editor {
            key?.let { pending[it] = value }
            return this
        }

        override fun remove(key: String?): SharedPreferences.Editor {
            key?.let { pending[it] = null }
            return this
        }

        override fun clear(): SharedPreferences.Editor {
            clearRequested = true
            return this
        }

        override fun commit(): Boolean {
            applyChanges()
            return true
        }

        override fun apply() {
            applyChanges()
        }

        private fun applyChanges() {
            if (clearRequested) {
                data.clear()
            }
            for ((key, value) in pending) {
                if (value == null) {
                    data.remove(key)
                } else {
                    data[key] = value
                }
            }
            pending.clear()
            clearRequested = false
        }
    }
}
