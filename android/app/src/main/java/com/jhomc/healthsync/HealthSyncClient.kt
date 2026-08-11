package com.jhomc.healthsync

import com.jhomc.healthsync.data.HealthOutboxEntity
import com.jhomc.healthsync.data.HealthRecordEntity
import java.io.IOException
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

const val SYNC_SCHEMA_VERSION = 1
const val MAX_BATCH_OPERATIONS = 500

data class ServerAck(val hcId: String, val revision: Long)
data class ServerRejection(val hcId: String, val revision: Long, val reason: String)

sealed class UploadOutcome {
    data class Accepted(val acked: List<ServerAck>, val rejected: List<ServerRejection>) : UploadOutcome()
    data class PermanentError(val detail: String) : UploadOutcome() // 400/401/413
    data class TransientError(val detail: String) : UploadOutcome() // red/5xx
}

/**
 * HTTPS-only delivery client. Builds bounded batches (contract §2/§4), sends
 * X-Sync-Token, and returns the per-operation acks. Never logs the token or
 * payload values.
 */
class HealthSyncClient(
    private val http: OkHttpClient = defaultClient(),
    private val nowEpochMs: () -> Long = { System.currentTimeMillis() },
) {

    fun validateTargetUrl(url: String, allowHttp: Boolean = false): Result<Unit> {
        val parsed = runCatching { java.net.URI(url) }.getOrNull()
            ?: return Result.failure(IllegalArgumentException("URL inválida"))
        return when (parsed.scheme) {
            "https" -> Result.success(Unit)
            "http" -> if (allowHttp) {
                Result.success(Unit)
            } else {
                Result.failure(IllegalArgumentException("HTTP está prohibido; usa HTTPS"))
            }
            null -> Result.failure(IllegalArgumentException("URL sin esquema; usa https://"))
            else -> Result.failure(IllegalArgumentException("Esquema no soportado: ${parsed.scheme}"))
        }
    }

    fun buildBatchPayload(
        deviceId: String,
        ops: List<HealthOutboxEntity>,
        records: Map<String, HealthRecordEntity?>,
    ): JSONObject {
        val operations = JSONArray()
        for (op in ops) {
            val record = records[op.hcId] ?: continue
            val item = JSONObject()
                .put("op", op.operation)
                .put("hc_id", op.hcId)
                .put("record_type", record.recordType)
                .put("revision", op.revision)
            if (op.operation == "UPSERT") {
                item.put("start_epoch_ms", record.startEpochMs)
                record.endEpochMs?.let { item.put("end_epoch_ms", it) }
                record.dataOriginPackage?.let { item.put("data_origin_package", it) }
                record.timeZoneOffsetMinutes?.let { item.put("time_zone_offset_minutes", it) }
                item.put("payload_schema_version", record.payloadSchemaVersion)
                item.put("value", JSONObject(record.valueJson))
            }
            operations.put(item)
        }
        return JSONObject()
            .put("schema_version", SYNC_SCHEMA_VERSION)
            .put("device_id", deviceId)
            .put("operations", operations)
    }

    /** POSTs one bounded batch. Never retries here; the worker decides. */
    fun postBatch(
        url: String,
        token: String,
        payload: JSONObject,
    ): UploadOutcome {
        val request = Request.Builder()
            .url(url)
            .addHeader("X-Sync-Token", token)
            .addHeader("Content-Type", "application/json; charset=utf-8")
            .post(payload.toString().toRequestBody(JSON_MEDIA_TYPE))
            .build()
        return try {
            http.newCall(request).execute().use { response ->
                when {
                    response.isSuccessful -> parseAck(response.body?.string())
                    response.code == 400 || response.code == 401 || response.code == 413 ->
                        UploadOutcome.PermanentError("HTTP ${response.code}")
                    else -> UploadOutcome.TransientError("HTTP ${response.code}")
                }
            }
        } catch (e: IOException) {
            UploadOutcome.TransientError(e.message ?: "red no disponible")
        }
    }

    private fun parseAck(body: String?): UploadOutcome {
        if (body == null) return UploadOutcome.TransientError("respuesta vacía")
        return runCatching {
            val json = JSONObject(body)
            val acked = json.getJSONArray("accepted").let { raw ->
                (0 until raw.length()).map { i ->
                    val item = raw.getJSONObject(i)
                    ServerAck(item.getString("hc_id"), item.getLong("revision"))
                }
            }
            val rejected = json.getJSONArray("rejected").let { raw ->
                (0 until raw.length()).map { i ->
                    val item = raw.getJSONObject(i)
                    ServerRejection(item.getString("hc_id"), item.getLong("revision"), item.getString("reason"))
                }
            }
            UploadOutcome.Accepted(acked, rejected)
        }.getOrElse { UploadOutcome.TransientError("acuse malformado") }
    }

    companion object {
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

        private fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .build()
    }
}
