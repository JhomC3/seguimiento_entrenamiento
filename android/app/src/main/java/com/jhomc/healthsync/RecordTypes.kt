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
)

object RecordTypes {

    /**
     * Catálogo ESENCIAL: solo los tipos que el dashboard realmente consume.
     * Los 13 del núcleo (Samsung Health los escribe) + 4 añadidos a petición
     * (distancia, VO2 máx, saturación de oxígeno y tasa metabólica basal).
     * Excluidos a propósito (superficie del SDK 1.1.0 que no aporta al
     * dashboard): elevación, velocidad, cadencias, potencia, pisos, empujes
     * de silla, HRV, frecuencia respiratoria, temperaturas, hidratación,
     * nutrición y todos los tipos sensibles/médicos (presión, glucosa, ciclo
     * menstrual, ovulación, actividad sexual).
     */
    val all: List<RecordTypeEntry> = listOf(
        // --- Núcleo (Samsung Health los escribe) ---
        entry("STEPS", StepsRecord::class, MappingFamily.INTERVAL, core = true),
        entry("HEART_RATE", HeartRateRecord::class, MappingFamily.SERIES, core = true, aggregated = true),
        entry("SLEEP_SESSION", SleepSessionRecord::class, MappingFamily.SESSION, core = true),
        entry("EXERCISE_SESSION", ExerciseSessionRecord::class, MappingFamily.SESSION, core = true),
        entry("ACTIVE_CALORIES_BURNED", ActiveCaloriesBurnedRecord::class, MappingFamily.INTERVAL, core = true),
        entry("TOTAL_CALORIES_BURNED", TotalCaloriesBurnedRecord::class, MappingFamily.INTERVAL, core = true),
        entry("RESTING_HEART_RATE", RestingHeartRateRecord::class, MappingFamily.INSTANT, core = true),
        entry("WEIGHT", WeightRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("HEIGHT", HeightRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("BODY_FAT", BodyFatRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("BONE_MASS", BoneMassRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("BODY_WATER_MASS", BodyWaterMassRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("LEAN_BODY_MASS", LeanBodyMassRecord::class, MappingFamily.COMPOSITION, core = true),

        // --- Añadidos a petición del usuario ---
        entry("DISTANCE", DistanceRecord::class, MappingFamily.INTERVAL),
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
) = RecordTypeEntry(
    typeName = typeName,
    recordClass = recordClass,
    permission = HealthPermission.getReadPermission(recordClass),
    family = family,
    sensitivity = sensitivity,
    core = core,
    aggregated = aggregated,
)
