plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp") version "2.1.0-1.0.29"
    id("jacoco")
}

android {
    namespace = "com.jhomc.healthsync"
    compileSdk = 36

    buildFeatures {
        buildConfig = true
    }

    defaultConfig {
        applicationId = "com.jhomc.healthsync"
        minSdk = 26
        targetSdk = 36
        // 2/0.2.0: fix 400 (cuarentena+bisección) + agregados horarios *_H1.
        // 4/0.3.0: escritura nutricional a Health Connect (permiso WRITE_NUTRITION).
        // 5/0.4.0: respiración pautada B5.0 (pacer + presets + historial).
        // 6/0.4.1: audio continuo gapless + planillas + círculo exclusivo.
        // 7/0.4.2: costura suspiro (no corte) + reloj de pared sin deriva.
        // 8/0.4.3: chiff de fraseo + tick 50 ms (giro clavado).
        // 9/0.4.4: marcado por altura + stream único + color fundido.
        // 10/0.4.5: ahogo por tañido (fin del transpuesto) + tono limpio.
        // 11/0.4.6: REST entre fases (silencio que extiende) + pull acotado.
        // Subir versionCode en cada build entregado: es la única forma de
        // distinguir APKs en Ajustes.
        versionCode = 28
        versionName = "0.4.23"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildTypes {
        debug {
            // Destino preconfigurado (solo debug): la app funciona sin tocar
            // nada. El token se lee del archivo gitignored del repo (fuente
            // única con el servidor); si falta, queda vacío y la app lo avisa.
            val token = syncDefaultToken()
            buildConfigField("String", "DEFAULT_SYNC_URL", "\"http://192.168.1.5:8000/sync/health-connect\"")
            buildConfigField("String", "DEFAULT_SYNC_TOKEN", "\"${token.escapeForKotlin()}\"")
            // Base explícita de la API v1 del diario (sin derivar por strip en
            // el caso común debug; ver TrainingApiClient.resolveApiBase).
            buildConfigField("String", "DEFAULT_API_BASE", "\"http://192.168.1.5:8000\"")
        }
        release {
            // Nunca embebir el secreto en un APK distribuible: release exige
            // configuración manual (o pairing QR futuro) para sincronizar.
            buildConfigField("String", "DEFAULT_SYNC_URL", "\"\"")
            buildConfigField("String", "DEFAULT_SYNC_TOKEN", "\"\"")
            buildConfigField("String", "DEFAULT_API_BASE", "\"\"")
        }
    }

    testOptions {
        unitTests {
            // Robolectric con la tabla de recursos de la app (colores, estilos,
            // fuentes): sin esto getColor(R.color.*) lanza NotFound y la UI del
            // pacer no se puede construir en los tests.
            isIncludeAndroidResources = true
        }
    }
}

jacoco {
    // 0.8.12: soporte de bytecode Java 17 (jvmTarget del módulo).
    toolVersion = "0.8.12"
}

// Robolectric define las clases de la app sin code-source (sandbox): sin
// includeNoLocationClasses JaCoCo las salta y toda la UI sale al 0 %.
// jdk.internal.** NO: instrumentar los Generated* dinámicos rompe la
// serialización del worker (NoClassDefFoundError en serialization).
// (Extensión nombrada: dentro de configureEach, `jacoco { }` sin más resuelve
// al jacoco de proyecto, no al de la tarea.)
tasks.withType<Test>().configureEach {
    val jacocoExt = extensions.getByType<org.gradle.testing.jacoco.plugins.JacocoTaskExtension>()
    jacocoExt.isIncludeNoLocationClasses = true
    jacocoExt.excludes = listOf("org.robolectric.**", "jdk.internal.**")
}

/** Informe de cobertura de testDebugUnitTest (JVM/Robolectric). */
tasks.register<JacocoReport>("jacocoTestReport") {
    group = "verification"
    description = "Cobertura de los tests unitarios (unitarios Robolectric)."
    dependsOn("testDebugUnitTest")
    classDirectories.setFrom(
        fileTree(layout.buildDirectory.dir("tmp/kotlin-classes/debug")) {
            include("com/jhomc/healthsync/**/*.class")
            exclude("**/R.class", "**/R\$*.class", "**/BuildConfig.class")
        },
    )
    sourceDirectories.setFrom(files("src/main/java"))
    executionData.setFrom(fileTree(layout.buildDirectory) { include("jacoco/*.exec") })
    reports {
        xml.required.set(true)
        html.required.set(true)
    }
}

fun syncDefaultToken(): String {
    // OJO: el root del proyecto Gradle es android/ (ahí vive settings.gradle),
    // no la raíz del repo. project.file() resuelve contra android/app/.
    // Ambas formas llegan a <repo>/data/hc_sync_token; con "data/..." a secas
    // se apuntaba a android/[app/]data/... (inexistente) y el debug salía con
    // token vacío -> "sin_destino" en cada sync.
    val file = rootProject.file("../data/hc_sync_token")
    return if (file.exists()) file.readText().trim() else ""
}

fun String.escapeForKotlin(): String =
    replace("\\", "\\\\").replace("\"", "\\\"").replace("$", "\\$")

dependencies {
    implementation("androidx.health.connect:connect-client:1.1.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")
    implementation("androidx.work:work-runtime-ktx:2.10.1")
    implementation("androidx.datastore:datastore-preferences:1.1.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.14.1")
    testImplementation("androidx.test:core:1.6.1")
    testImplementation("org.json:json:20240303")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}
