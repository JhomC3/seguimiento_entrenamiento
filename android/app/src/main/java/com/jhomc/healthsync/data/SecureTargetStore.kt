package com.jhomc.healthsync.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import java.security.SecureRandom

private val Context.syncStore by preferencesDataStore(name = "sync_targets")

private val KEY_URL = stringPreferencesKey("target_url")
private val KEY_NAME = stringPreferencesKey("target_name")
private val KEY_DEVICE_ID = stringPreferencesKey("device_id")

private const val KEYSTORE_ALIAS = "health_sync_token"

/**
 * Non-secret preferences (URL, target name, device id) live in DataStore.
 * The sync token is encrypted with an Android Keystore AES key; only the
 * ciphertext touches disk.
 */
class SecureTargetStore(private val context: Context) {

    suspend fun saveTarget(url: String, name: String) {
        context.syncStore.edit { prefs ->
            prefs[KEY_URL] = url
            prefs[KEY_NAME] = name
        }
    }

    suspend fun target(): Target? {
        val prefs = context.syncStore.data.first()
        val url = prefs[KEY_URL] ?: return null
        return Target(url = url, name = prefs[KEY_NAME] ?: "")
    }

    suspend fun saveToken(token: String) {
        require(isValidSyncToken(token)) {
            "Token inválido: solo ASCII imprimible (sin espacios ni caracteres raros). " +
                "Se detectó un carácter no ASCII — suele ser un guion largo (—) colado en el copiado/pegado."
        }
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, keystoreKey())
        val iv = cipher.iv
        val encrypted = cipher.doFinal(token.toByteArray(Charsets.UTF_8))
        context.syncStore.edit { prefs ->
            prefs[stringPreferencesKey("token_enc")] = Base64.encodeToString(encrypted, Base64.NO_WRAP)
            prefs[stringPreferencesKey("token_iv")] = Base64.encodeToString(iv, Base64.NO_WRAP)
        }
    }

    suspend fun token(): String? {
        val prefs = context.syncStore.data.first()
        val enc = prefs[stringPreferencesKey("token_enc")] ?: return null
        val iv = prefs[stringPreferencesKey("token_iv")] ?: return null
        return runCatching {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE,
                keystoreKey(),
                GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)),
            )
            String(cipher.doFinal(Base64.decode(enc, Base64.NO_WRAP)), Charsets.UTF_8)
        }.getOrNull()
    }

    suspend fun clearTarget() {
        context.syncStore.edit { it.clear() }
    }

    suspend fun deviceId(): String {
        val existing = context.syncStore.data.first().get(KEY_DEVICE_ID)
        if (existing != null) return existing
        val id = "android-" + SecureRandom().let { r ->
            val bytes = ByteArray(10)
            r.nextBytes(bytes)
            bytes.joinToString("") { "%02x".format(it) }
        }
        context.syncStore.edit { prefs -> prefs[KEY_DEVICE_ID] = id }
        return id
    }

    private fun keystoreKey(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(KEYSTORE_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                KEYSTORE_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build(),
        )
        return generator.generateKey()
    }

    data class Target(val url: String, val name: String)

    companion object {
        private const val TRANSFORMATION = "AES/GCM/NoPadding"

        /**
         * X-Sync-Token travels in an HTTP header: only printable ASCII is
         * allowed (no spaces, no Unicode dashes from copy/paste).
         */
        fun isValidSyncToken(token: String): Boolean =
            token.isNotEmpty() && token.all { it.code in 0x21..0x7E }
    }
}

private suspend fun androidx.datastore.core.DataStore<Preferences>.firstOrNullSafe(): Preferences? =
    runCatching { this.data.first() }.getOrNull()
