package com.jhomc.healthsync

import androidx.health.connect.client.permission.HealthPermission
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
import kotlin.reflect.KClass

enum class MappingFamily { INTERVAL, INSTANT, SERIES, SESSION, COMPOSITION, ROUTE, MEDICAL }

enum class Sensitivity { NORMAL, SENSITIVE }

/**
 * One explicit entry per Record type of the pinned SDK (connect-client 1.1.0).
 * The class list is verified against the actual AAR (records package, 64
 * classes). Permissions always resolve via HealthPermission.getReadPermission,
 * never via hard-coded permission strings.
 */
data class RecordTypeEntry(
    val typeName: String,
    val recordClass: KClass<out Record>,
    val permission: String,
    val family: MappingFamily,
    val sensitivity: Sensitivity = Sensitivity.NORMAL,
    /** Core batch: types Samsung Health actually writes; requested first. */
    val core: Boolean = false,
)

object RecordTypes {

    val all: List<RecordTypeEntry> = listOf(
        // --- Núcleo (lote inicial de permisos; Samsung Health los escribe) ---
        entry("STEPS", StepsRecord::class, MappingFamily.INTERVAL, core = true),
        entry("HEART_RATE", HeartRateRecord::class, MappingFamily.SERIES, core = true),
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

        // --- Ejercicio (métricas de sesión; opcional) ---
        // EXERCISE_ROUTE no está en el catálogo: ExerciseRoute no extiende
        // Record y se lee con API propia (readExerciseRoute) ligada a una
        // ExerciseSessionRecord; non-goal v1. Mindfulness/PlannedExercise son
        // APIs experimentales en 1.1.0 y tampoco se prometen.
        entry("DISTANCE", DistanceRecord::class, MappingFamily.INTERVAL),
        entry("ELEVATION_GAINED", ElevationGainedRecord::class, MappingFamily.INTERVAL),
        entry("SPEED", SpeedRecord::class, MappingFamily.SERIES),
        entry("STEPS_CADENCE", StepsCadenceRecord::class, MappingFamily.SERIES),
        entry("CYCLING_PEDALING_CADENCE", CyclingPedalingCadenceRecord::class, MappingFamily.SERIES),
        entry("POWER", PowerRecord::class, MappingFamily.SERIES),
        entry("FLOORS_CLIMBED", FloorsClimbedRecord::class, MappingFamily.INSTANT),
        entry("WHEELCHAIR_PUSHES", WheelchairPushesRecord::class, MappingFamily.INSTANT),
        entry("VO2_MAX", Vo2MaxRecord::class, MappingFamily.INSTANT),

        // --- Fisiología (opcional) ---
        entry("HEART_RATE_VARIABILITY_RMSSD", HeartRateVariabilityRmssdRecord::class, MappingFamily.INSTANT),
        entry("OXYGEN_SATURATION", OxygenSaturationRecord::class, MappingFamily.SERIES),
        entry("RESPIRATORY_RATE", RespiratoryRateRecord::class, MappingFamily.INSTANT),
        entry("SKIN_TEMPERATURE", SkinTemperatureRecord::class, MappingFamily.SERIES),
        entry("BODY_TEMPERATURE", BodyTemperatureRecord::class, MappingFamily.INSTANT),
        entry("BASAL_BODY_TEMPERATURE", BasalBodyTemperatureRecord::class, MappingFamily.INSTANT),
        entry("BASAL_METABOLIC_RATE", BasalMetabolicRateRecord::class, MappingFamily.INSTANT),

        // --- Nutrición e hidratación (opcional) ---
        entry("HYDRATION", HydrationRecord::class, MappingFamily.INTERVAL),
        entry("NUTRITION", NutritionRecord::class, MappingFamily.INTERVAL),

        // --- Recursos médicos (sensibles; explicación previa) ---
        entry("BLOOD_PRESSURE", BloodPressureRecord::class, MappingFamily.MEDICAL, sensitivity = Sensitivity.SENSITIVE),
        entry("BLOOD_GLUCOSE", BloodGlucoseRecord::class, MappingFamily.MEDICAL, sensitivity = Sensitivity.SENSITIVE),
        entry("CERVICAL_MUCUS", CervicalMucusRecord::class, MappingFamily.MEDICAL, sensitivity = Sensitivity.SENSITIVE),
        entry("MENSTRUATION_FLOW", MenstruationFlowRecord::class, MappingFamily.INTERVAL, sensitivity = Sensitivity.SENSITIVE),
        entry("MENSTRUATION_PERIOD", MenstruationPeriodRecord::class, MappingFamily.INTERVAL, sensitivity = Sensitivity.SENSITIVE),
        entry("INTERMENSTRUAL_BLEEDING", IntermenstrualBleedingRecord::class, MappingFamily.INTERVAL, sensitivity = Sensitivity.SENSITIVE),
        entry("OVULATION_TEST", OvulationTestRecord::class, MappingFamily.INSTANT, sensitivity = Sensitivity.SENSITIVE),
        entry("SEXUAL_ACTIVITY", SexualActivityRecord::class, MappingFamily.INSTANT, sensitivity = Sensitivity.SENSITIVE),
    )

    /**
     * Not in the catalog: FHIR medical resources (MedicalResource) are not
     * `Record` types and use their own API + permissions; non-goal v1.
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
) = RecordTypeEntry(
    typeName = typeName,
    recordClass = recordClass,
    permission = HealthPermission.getReadPermission(recordClass),
    family = family,
    sensitivity = sensitivity,
    core = core,
)
