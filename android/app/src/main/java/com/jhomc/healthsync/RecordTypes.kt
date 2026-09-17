package com.jhomc.healthsync

import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ActiveCaloriesBurnedRecord
import androidx.health.connect.client.records.BasalMetabolicRateRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.BodyWaterMassRecord
import androidx.health.connect.client.records.BoneMassRecord
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeightRecord
import androidx.health.connect.client.records.LeanBodyMassRecord
import androidx.health.connect.client.records.OxygenSaturationRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.Vo2MaxRecord
import androidx.health.connect.client.records.WeightRecord
import kotlin.reflect.KClass

enum class MappingFamily { INTERVAL, INSTANT, SERIES, SESSION, COMPOSITION }

enum class Sensitivity { NORMAL, SENSITIVE }

/**
 * One explicit entry per Record type of the pinned SDK (connect-client 1.1.0).
 * Permissions always resolve via HealthPermission.getReadPermission, never via
 * hard-coded permission strings.
 */
data class RecordTypeEntry(
    val typeName: String,
    val recordClass: KClass<out Record>,
    val permission: String,
    val family: MappingFamily,
    val sensitivity: Sensitivity = Sensitivity.NORMAL,
    /** Core batch: types Samsung Health actually writes; requested first. */
    val core: Boolean = false,
    /**
     * El sync NO lee el crudo de este tipo: se lee por días acotados y se
     * sube agregado (p. ej. HEART_RATE → tramos de 5 min) porque su serie
     * cruda es densa y la paginación del proveedor es poco fiable.
     */
    val aggregated: Boolean = false,
    /**
     * Agregado por SUMA HORARIA (STEPS_H1 y cía.): como [aggregated], pero el
     * tramo es 1 h con el valor sumado. [historyDays] acota el bootstrap:
     * corte hacia adelante (el histórico crudo ya está en el servidor).
     */
    val hourlySum: Boolean = false,
    val historyDays: Int = 30,
)

object RecordTypes {

    /**
     * Catálogo ESENCIAL: solo los tipos que el dashboard realmente consume.
     * Núcleo (Samsung Health los escribe) + añadidos a petición (distancia,
     * VO2 máx, saturación de oxígeno y tasa metabólica basal). Pasos, calorías
     * y distancia viajan como TOTALES HORARIOS (*_H1, ver HourlySumBucketizer):
     * su granularidad cruda no aporta al dashboard y saturaba el outbox.
     * Excluidos a propósito (superficie del SDK 1.1.0 que no aporta al
     * dashboard): elevación, velocidad, cadencias, potencia, pisos, empujes
     * de silla, HRV, frecuencia respiratoria, temperaturas, hidratación,
     * nutrición y todos los tipos sensibles/médicos (presión, glucosa, ciclo
     * menstrual, ovulación, actividad sexual).
     */
    val all: List<RecordTypeEntry> = listOf(
        // --- Núcleo (Samsung Health los escribe) ---
        entry("STEPS_H1", StepsRecord::class, MappingFamily.INTERVAL, core = true, hourlySum = true, historyDays = 4),
        entry("HEART_RATE", HeartRateRecord::class, MappingFamily.SERIES, core = true, aggregated = true),
        entry("SLEEP_SESSION", SleepSessionRecord::class, MappingFamily.SESSION, core = true),
        entry("EXERCISE_SESSION", ExerciseSessionRecord::class, MappingFamily.SESSION, core = true),
        entry("ACTIVE_CALORIES_H1", ActiveCaloriesBurnedRecord::class, MappingFamily.INTERVAL, core = true, hourlySum = true, historyDays = 4),
        entry("TOTAL_CALORIES_H1", TotalCaloriesBurnedRecord::class, MappingFamily.INTERVAL, core = true, hourlySum = true, historyDays = 4),
        entry("RESTING_HEART_RATE", RestingHeartRateRecord::class, MappingFamily.INSTANT, core = true),
        entry("WEIGHT", WeightRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("HEIGHT", HeightRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("BODY_FAT", BodyFatRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("BONE_MASS", BoneMassRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("BODY_WATER_MASS", BodyWaterMassRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("LEAN_BODY_MASS", LeanBodyMassRecord::class, MappingFamily.COMPOSITION, core = true),

        // --- Añadidos a petición del usuario ---
        entry("DISTANCE_H1", DistanceRecord::class, MappingFamily.INTERVAL, hourlySum = true, historyDays = 4),
        entry("VO2_MAX", Vo2MaxRecord::class, MappingFamily.INSTANT),
        entry("OXYGEN_SATURATION", OxygenSaturationRecord::class, MappingFamily.SERIES),
        entry("BASAL_METABOLIC_RATE", BasalMetabolicRateRecord::class, MappingFamily.INSTANT),
    )

    /**
     * SleepStage data travels inside SleepSessionRecord (1.1.0 removed the
     * standalone record). ExerciseRoute uses its own API tied to a session.
     */
    val core: List<RecordTypeEntry> = all.filter { it.core }

    val optionalByFamily: Map<MappingFamily, List<RecordTypeEntry>> =
        all.filterNot { it.core }.groupBy { it.family }

    fun byTypeName(typeName: String): RecordTypeEntry? = all.firstOrNull { it.typeName == typeName }

    fun byClass(recordClass: KClass<out Record>): RecordTypeEntry? =
        all.firstOrNull { it.recordClass == recordClass }
}

private fun entry(
    typeName: String,
    recordClass: KClass<out Record>,
    family: MappingFamily,
    core: Boolean = false,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    aggregated: Boolean = false,
    hourlySum: Boolean = false,
    historyDays: Int = 30,
) = RecordTypeEntry(
    typeName = typeName,
    recordClass = recordClass,
    permission = HealthPermission.getReadPermission(recordClass),
    family = family,
    sensitivity = sensitivity,
    core = core,
    aggregated = aggregated,
    hourlySum = hourlySum,
    historyDays = historyDays,
)
