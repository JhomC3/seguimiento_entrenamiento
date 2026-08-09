package com.jhomc.healthsync.data

import androidx.health.connect.client.records.ActiveCaloriesBurnedRecord
import androidx.health.connect.client.records.BasalBodyTemperatureRecord
import androidx.health.connect.client.records.BasalMetabolicRateRecord
import androidx.health.connect.client.records.BloodGlucoseRecord
import androidx.health.connect.client.records.BloodPressureRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.BodyTemperatureRecord
import androidx.health.connect.client.records.BodyWaterMassRecord
import androidx.health.connect.client.records.BoneMassRecord
import androidx.health.connect.client.records.CervicalMucusRecord
import androidx.health.connect.client.records.CyclingPedalingCadenceRecord
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.ElevationGainedRecord
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.FloorsClimbedRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeartRateVariabilityRmssdRecord
import androidx.health.connect.client.records.HeightRecord
import androidx.health.connect.client.records.HydrationRecord
import androidx.health.connect.client.records.IntermenstrualBleedingRecord
import androidx.health.connect.client.records.LeanBodyMassRecord
import androidx.health.connect.client.records.MenstruationFlowRecord
import androidx.health.connect.client.records.MenstruationPeriodRecord
import androidx.health.connect.client.records.NutritionRecord
import androidx.health.connect.client.records.OvulationTestRecord
import androidx.health.connect.client.records.OxygenSaturationRecord
import androidx.health.connect.client.records.PowerRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.RespiratoryRateRecord
import androidx.health.connect.client.records.SexualActivityRecord
import androidx.health.connect.client.records.SkinTemperatureRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.SpeedRecord
import androidx.health.connect.client.records.StepsCadenceRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.Vo2MaxRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.records.WheelchairPushesRecord
import com.jhomc.healthsync.RecordTypeEntry
import com.jhomc.healthsync.RecordTypes
import java.time.Instant
import org.json.JSONArray
import org.json.JSONObject

const val PAYLOAD_SCHEMA_VERSION = 1

/**
 * Deterministic Record -> JSON mapping. Explicit per type (no reflection):
 * a catalog entry without mapper is rejected locally with a clear diagnostic,
 * never serialized partially. Output shape follows health-sync-contract.md §4.
 */
object RecordMappers {

    fun hasMapper(entry: RecordTypeEntry): Boolean = entry.typeName in mappedTypes

    private val mappedTypes: Set<String> =
        RecordTypes.all.mapTo(mutableSetOf()) { it.typeName }

    fun toPayload(record: Record): JSONObject {
        val entry = RecordTypes.byClass(record::class)
            ?: throw IllegalArgumentException("Tipo fuera del catálogo: ${record::class.simpleName}")
        val base = JSONObject()
        base.put("hc_id", record.metadata.id)
        base.put("record_type", entry.typeName)
        base.put("revision", record.metadata.lastModifiedTime.toEpochMilli())
        intervalStart(record)?.let { base.put("start_epoch_ms", it.toEpochMilli()) }
        intervalEnd(record)?.let { base.put("end_epoch_ms", it.toEpochMilli()) }
        record.metadata.dataOrigin.packageName?.let { base.put("data_origin_package", it) }
        zoneOffsetMinutes(record)?.let { base.put("time_zone_offset_minutes", it) }
        base.put("payload_schema_version", PAYLOAD_SCHEMA_VERSION)
        base.put("value", valueOf(record, entry))
        return base
    }

    fun toPayloadJson(record: Record): String = toPayload(record).toString()

    private fun valueOf(record: Record, entry: RecordTypeEntry): JSONObject =
        when (record) {
            is StepsRecord -> JSONObject().put("count", record.count)
            is HeartRateRecord -> JSONObject().put("samples", JSONArray().apply {
                record.samples.forEach { s ->
                    put(JSONObject().put("time", s.time.toEpochMilli()).put("bpm", s.beatsPerMinute))
                }
            })
            is SleepSessionRecord -> JSONObject().apply {
                record.title?.let { put("title", it) }
                record.notes?.let { put("notes", it) }
                put("stages", JSONArray().apply {
                    record.stages.forEach { stage ->
                        put(JSONObject()
                            .put("start_epoch_ms", stage.startTime.toEpochMilli())
                            .put("end_epoch_ms", stage.endTime.toEpochMilli())
                            .put("stage", stage.stage))
                    }
                })
            }
            is ExerciseSessionRecord -> JSONObject().apply {
                record.title?.let { put("title", it) }
                record.notes?.let { put("notes", it) }
                put("exercise_type", record.exerciseType)
                put("segments", JSONArray().apply {
                    record.segments.forEach { seg ->
                        put(JSONObject()
                            .put("start_epoch_ms", seg.startTime.toEpochMilli())
                            .put("end_epoch_ms", seg.endTime.toEpochMilli())
                            .put("segment_type", seg.segmentType)
                            .put("repetitions", seg.repetitions))
                    }
                })
            }
            is ActiveCaloriesBurnedRecord -> JSONObject().put("energy_kcal", record.energy.inKilocalories)
            is TotalCaloriesBurnedRecord -> JSONObject().put("energy_kcal", record.energy.inKilocalories)
            is WeightRecord -> JSONObject().put("kg", record.weight.inKilograms)
            is HeightRecord -> JSONObject().put("meters", record.height.inMeters)
            is BodyFatRecord -> JSONObject().put("percentage", record.percentage.value)
            is BoneMassRecord -> JSONObject().put("kg", record.mass.inKilograms)
            is BodyWaterMassRecord -> JSONObject().put("kg", record.mass.inKilograms)
            is LeanBodyMassRecord -> JSONObject().put("kg", record.mass.inKilograms)
            is RestingHeartRateRecord -> JSONObject().put("bpm", record.beatsPerMinute)
            is HeartRateVariabilityRmssdRecord -> JSONObject().put("rmssd_ms", record.heartRateVariabilityMillis)
            is OxygenSaturationRecord -> JSONObject().put("percentage", record.percentage.value)
            is RespiratoryRateRecord -> JSONObject().put("breaths_per_minute", record.rate)
            is SkinTemperatureRecord -> JSONObject().apply {
                record.baseline?.let { put("baseline_c", it.inCelsius) }
                put("deltas", JSONArray().apply {
                    record.deltas.forEach { d ->
                        put(JSONObject().put("time", d.time.toEpochMilli()).put("delta_c", d.delta.inCelsius))
                    }
                })
            }
            is BodyTemperatureRecord -> JSONObject().put("temperature_c", record.temperature.inCelsius)
            is BasalBodyTemperatureRecord -> JSONObject().put("temperature_c", record.temperature.inCelsius)
            is BasalMetabolicRateRecord -> JSONObject().put("kcal_per_day", record.basalMetabolicRate.inKilocaloriesPerDay)
            is Vo2MaxRecord -> JSONObject().put("vo2_max_ml_kg_min", record.vo2MillilitersPerMinuteKilogram)
            is DistanceRecord -> JSONObject().put("meters", record.distance.inMeters)
            is ElevationGainedRecord -> JSONObject().put("meters", record.elevation.inMeters)
            is SpeedRecord -> JSONObject().put("samples", JSONArray().apply {
                record.samples.forEach { s ->
                    put(JSONObject().put("time", s.time.toEpochMilli()).put("meters_per_second", s.speed.inMetersPerSecond))
                }
            })
            is StepsCadenceRecord -> JSONObject().put("samples", JSONArray().apply {
                record.samples.forEach { s ->
                    put(JSONObject().put("time", s.time.toEpochMilli()).put("rpm", s.rate))
                }
            })
            is CyclingPedalingCadenceRecord -> JSONObject().put("samples", JSONArray().apply {
                record.samples.forEach { s ->
                    put(JSONObject().put("time", s.time.toEpochMilli()).put("rpm", s.revolutionsPerMinute))
                }
            })
            is PowerRecord -> JSONObject().put("samples", JSONArray().apply {
                record.samples.forEach { s ->
                    put(JSONObject().put("time", s.time.toEpochMilli()).put("watts", s.power.inWatts))
                }
            })
            is FloorsClimbedRecord -> JSONObject().put("count", record.floors)
            is WheelchairPushesRecord -> JSONObject().put("count", record.count)
            is HydrationRecord -> JSONObject().put("volume_ml", record.volume.inMilliliters)
            is NutritionRecord -> JSONObject().apply {
                record.energy?.let { put("energy_kcal", it.inKilocalories) }
                record.protein?.let { put("protein_g", it.inGrams) }
                record.totalFat?.let { put("total_fat_g", it.inGrams) }
                record.totalCarbohydrate?.let { put("total_carbohydrate_g", it.inGrams) }
                record.dietaryFiber?.let { put("fiber_g", it.inGrams) }
                record.sugar?.let { put("sugar_g", it.inGrams) }
            }
            is BloodPressureRecord -> JSONObject().apply {
                put("systolic_mmhg", record.systolic.inMillimetersOfMercury)
                put("diastolic_mmhg", record.diastolic.inMillimetersOfMercury)
            }
            is BloodGlucoseRecord -> JSONObject().put("mg_per_dl", record.level.inMilligramsPerDeciliter)
            is CervicalMucusRecord -> JSONObject().apply {
                put("appearance", record.appearance)
                put("sensation", record.sensation)
            }
            is MenstruationFlowRecord -> JSONObject().put("flow_type", record.flow)
            is MenstruationPeriodRecord -> JSONObject()
            is IntermenstrualBleedingRecord -> JSONObject()
            is OvulationTestRecord -> JSONObject().put("result", record.result)
            is SexualActivityRecord -> JSONObject().put("protection_used", record.protectionUsed)
            else -> throw IllegalArgumentException(
                "Tipo sin mapeador explícito: ${entry.typeName}. " +
                    "No se serializa por reflexión; añadir rama en RecordMappers.",
            )
        }

    /** start/end for interval-like records; null when the type is instantaneous. */
    private fun intervalBounds(record: Record): Pair<Instant, Instant?>? = when (record) {
        is StepsRecord -> Pair(record.startTime, record.endTime)
        is HeartRateRecord -> Pair(record.startTime, record.endTime)
        is SleepSessionRecord -> Pair(record.startTime, record.endTime)
        is ExerciseSessionRecord -> Pair(record.startTime, record.endTime)
        is ActiveCaloriesBurnedRecord -> Pair(record.startTime, record.endTime)
        is TotalCaloriesBurnedRecord -> Pair(record.startTime, record.endTime)
        is DistanceRecord -> Pair(record.startTime, record.endTime)
        is ElevationGainedRecord -> Pair(record.startTime, record.endTime)
        is SpeedRecord -> Pair(record.startTime, record.endTime)
        is StepsCadenceRecord -> Pair(record.startTime, record.endTime)
        is CyclingPedalingCadenceRecord -> Pair(record.startTime, record.endTime)
        is PowerRecord -> Pair(record.startTime, record.endTime)
        is SkinTemperatureRecord -> Pair(record.startTime, record.endTime)
        is HydrationRecord -> Pair(record.startTime, record.endTime)
        is NutritionRecord -> Pair(record.startTime, record.endTime)
        is FloorsClimbedRecord -> Pair(record.startTime, record.endTime)
        is WheelchairPushesRecord -> Pair(record.startTime, record.endTime)
        is MenstruationPeriodRecord -> Pair(record.startTime, record.endTime)
        else -> null
    }

    /** time for instantaneous records; null otherwise. */
    private fun instantTime(record: Record): Instant? = when (record) {
        is WeightRecord -> record.time
        is HeightRecord -> record.time
        is BodyFatRecord -> record.time
        is BoneMassRecord -> record.time
        is BodyWaterMassRecord -> record.time
        is LeanBodyMassRecord -> record.time
        is RestingHeartRateRecord -> record.time
        is HeartRateVariabilityRmssdRecord -> record.time
        is OxygenSaturationRecord -> record.time
        is RespiratoryRateRecord -> record.time
        is BodyTemperatureRecord -> record.time
        is BasalBodyTemperatureRecord -> record.time
        is BasalMetabolicRateRecord -> record.time
        is Vo2MaxRecord -> record.time
        is BloodPressureRecord -> record.time
        is BloodGlucoseRecord -> record.time
        is CervicalMucusRecord -> record.time
        is OvulationTestRecord -> record.time
        is SexualActivityRecord -> record.time
        is MenstruationFlowRecord -> record.time
        is IntermenstrualBleedingRecord -> record.time
        else -> null
    }

    private fun intervalStart(record: Record): Instant? {
        intervalBounds(record)?.let { return it.first }
        return instantTime(record)
    }

    private fun intervalEnd(record: Record): Instant? = intervalBounds(record)?.second

    private fun zoneOffsetMinutes(record: Record): Int? {
        val zone = when (record) {
            is StepsRecord -> record.startZoneOffset
            is HeartRateRecord -> record.startZoneOffset
            is SleepSessionRecord -> record.startZoneOffset
            is ExerciseSessionRecord -> record.startZoneOffset
            is ActiveCaloriesBurnedRecord -> record.startZoneOffset
            is TotalCaloriesBurnedRecord -> record.startZoneOffset
            is DistanceRecord -> record.startZoneOffset
            is ElevationGainedRecord -> record.startZoneOffset
            is SpeedRecord -> record.startZoneOffset
            is StepsCadenceRecord -> record.startZoneOffset
            is CyclingPedalingCadenceRecord -> record.startZoneOffset
            is PowerRecord -> record.startZoneOffset
            is SkinTemperatureRecord -> record.startZoneOffset
            is HydrationRecord -> record.startZoneOffset
            is NutritionRecord -> record.startZoneOffset
            is FloorsClimbedRecord -> record.startZoneOffset
            is WheelchairPushesRecord -> record.startZoneOffset
            is MenstruationPeriodRecord -> record.startZoneOffset
            is WeightRecord -> record.zoneOffset
            is HeightRecord -> record.zoneOffset
            is BodyFatRecord -> record.zoneOffset
            is BoneMassRecord -> record.zoneOffset
            is BodyWaterMassRecord -> record.zoneOffset
            is LeanBodyMassRecord -> record.zoneOffset
            is RestingHeartRateRecord -> record.zoneOffset
            is HeartRateVariabilityRmssdRecord -> record.zoneOffset
            is OxygenSaturationRecord -> record.zoneOffset
            is RespiratoryRateRecord -> record.zoneOffset
            is BodyTemperatureRecord -> record.zoneOffset
            is BasalBodyTemperatureRecord -> record.zoneOffset
            is BasalMetabolicRateRecord -> record.zoneOffset
            is Vo2MaxRecord -> record.zoneOffset
            is BloodPressureRecord -> record.zoneOffset
            is BloodGlucoseRecord -> record.zoneOffset
            is CervicalMucusRecord -> record.zoneOffset
            is OvulationTestRecord -> record.zoneOffset
            is SexualActivityRecord -> record.zoneOffset
            is MenstruationFlowRecord -> record.zoneOffset
            is IntermenstrualBleedingRecord -> record.zoneOffset
            else -> null
        }
        return zone?.totalSeconds?.div(60)
    }
}
